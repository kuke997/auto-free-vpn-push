import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
from urllib.parse import urljoin, quote
import time
import random
import logging

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
BASE_URL = "https://nodefree.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
    "TE": "Trailers"
}

def get_threads_on_page(page):
    """
    从 nodefree.net 列表页中提取所有文章链接
    """
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}/page/{page}"
    
    logger.info(f"🔍 正在爬取页面: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        threads = []
        
        # 查找所有文章链接 - 更精确的选择器
        article_links = soup.select('a.list-group-item')
        if not article_links:
            # 备用选择器
            article_links = soup.select('a[href*="/p/"]')
        
        for link in article_links:
            href = link.get('href')
            if href and '/p/' in href:
                full_url = urljoin(BASE_URL, href)
                if full_url not in threads:
                    threads.append(full_url)
        
        logger.info(f"✅ 找到 {len(threads)} 篇文章")
        return threads
    
    except Exception as e:
        logger.error(f"⚠️ 获取页面失败 {url} 错误: {str(e)}")
        return []

def extract_yaml_links_from_thread(url):
    """
    从单个文章页面中提取所有订阅链接 - 修复版
    """
    logger.info(f"📝 正在解析文章: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = set()
        
        # 只提取特定类型的链接，避免文章链接
        domains = [
            'githubrowcontent', 'github.io', 'sub-store', 
            'subscribe', 'clash', 'v2ray', 'youlink',
            'raw.githubusercontent.com', 'cdn.jsdelivr.net'
        ]
        
        # 1. 查找所有链接元素
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # 跳过讨论主题链接
            if '/t/' in href or '/p/' in href:
                continue
                
            # 检查是否是订阅链接
            if any(ext in href for ext in ['.yaml', '.yml', '.txt']):
                links.add(href)
            
            # 检查是否包含特定域名
            elif any(domain in href for domain in domains):
                links.add(href)
        
        # 2. 查找内容中的直接链接
        content = soup.select_one('div.content') or soup.select_one('div.post-content')
        if content:
            # 更精确的正则表达式匹配订阅链接
            text_links = re.findall(r'https?://[^\s"\']+?\.(?:ya?ml|txt)\b', content.text, re.I)
            links.update(text_links)
            
            # 匹配特定域名的链接
            domain_pattern = r'https?://(?:{})[^\s"\']+'.format('|'.join(domains))
            domain_links = re.findall(domain_pattern, content.text, re.I)
            links.update(domain_links)
        
        # 3. 查找代码块中的订阅链接
        for code_block in soup.select('pre, code'):
            code_text = code_block.get_text()
            # 匹配常见的订阅格式
            config_links = re.findall(
                r'https?://[^\s"\']+?\.(?:ya?ml|txt)\b', 
                code_text, 
                re.I
            )
            links.update(config_links)
            
            # 匹配base64编码的订阅链接
            base64_links = re.findall(
                r'(?:ss|ssr|vmess|trojan)://[a-zA-Z0-9+/]+={0,2}', 
                code_text
            )
            links.update(base64_links)
        
        # 过滤掉无效链接
        filtered_links = set()
        for link in links:
            # 跳过讨论主题链接
            if '/t/' in link or '/p/' in link:
                continue
                
            # 确保是完整URL
            if link.startswith('//'):
                link = 'https:' + link
            elif link.startswith('/'):
                link = urljoin(BASE_URL, link)
                
            # 确保是HTTP/HTTPS协议
            if link.startswith('http'):
                filtered_links.add(link)
        
        logger.info(f"   🔗 提取到 {len(filtered_links)} 个订阅链接")
        return list(filtered_links)
    
    except Exception as e:
        logger.error(f"⚠️ 解析帖子失败 {url} 错误: {str(e)}")
        return []

def validate_subscription(url):
    """
    验证订阅链接是否有效 - 更严格的验证
    """
    logger.info(f"🔐 正在验证链接: {url}")
    
    try:
        time.sleep(random.uniform(0.5, 1.5))
        
        # 处理可能的相对URL
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url
            
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            logger.warning(f"    ❌ HTTP {res.status_code}: {url}")
            return False
        
        content = res.text
        
        # 更严格的VPN配置检测
        vpn_keywords = [
            "proxies:", "proxy-providers:", "vmess://", "ss://", 
            "trojan://", "vless://", "clash:", "port:"
        ]
        
        for keyword in vpn_keywords:
            if keyword in content.lower():
                logger.info(f"    ✔️ 有效订阅: {url}")
                return True
        
        # 检查base64编码的配置
        if re.search(r'^[A-Za-z0-9+/]+={0,2}$', content.strip()):
            logger.info(f"    ✔️ 有效订阅 (Base64编码): {url}")
            return True
        
        logger.warning(f"    ❌ 无效订阅 (无VPN配置): {url}")
        return False
    
    except Exception as e:
        logger.error(f"    ❌ 验证异常: {url}，错误: {str(e)}")
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    """
    将有效订阅链接推送到 Telegram 频道 - 改进版
    """
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return
    
    # 创建消息内容
    text = "🆕 <b>NodeFree 最新免费VPN订阅链接</b>\n\n"
    text += "更新时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
    text += "以下是可直接导入VPN客户端的订阅链接：\n\n"
    
    for i, u in enumerate(urls[:10], 1):
        safe = quote(u, safe=":/?=&")
        # 缩短显示的长链接
        display_url = u.split('/')[-1] if '/' in u else u  # 显示文件名部分
        text += f"{i}. <code>{display_url}</code>\n"
        text += f"   <a href=\"{safe}\">点击复制订阅链接</a>\n\n"
    
    text += "⚠️ 仅供学习使用，请遵守当地法律法规\n"
    text += "🔒 订阅链接有效期通常为1-7天"
    
    # 控制消息长度
    if len(text) > 4096:
        text = text[:4000] + "\n\n...（部分链接已省略）"
    
    bot = Bot(token=bot_token)
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info("✅ 推送成功")
    except Exception as e:
        logger.error(f"❌ 推送失败: {str(e)}")

async def main():
    logger.info("="*50)
    logger.info(f"🌐 NodeFree 免费节点爬虫启动 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
    
    all_links = set()
    valid_links = []
    
    # 爬取前2页内容即可
    for page in range(1, 3):
        threads = get_threads_on_page(page)
        
        if not threads:
            logger.warning(f"⚠️ 第 {page} 页未找到文章，跳过")
            continue
            
        time.sleep(random.uniform(1, 3))
        
        for t in threads:
            subs = extract_yaml_links_from_thread(t)
            all_links.update(subs)
            
            time.sleep(random.uniform(0.5, 2))
    
    logger.info(f"\n🔍 共提取到 {len(all_links)} 条订阅链接，开始验证...")
    
    # 优先验证特定类型的链接
    for link in all_links:
        # 优先验证.yaml/.yml链接
        if any(ext in link for ext in ['.yaml', '.yml', '.txt']):
            if validate_subscription(link):
                valid_links.append(link)
    
    # 然后验证其他链接
    for link in all_links:
        if link not in valid_links:
            if validate_subscription(link):
                valid_links.append(link)
    
    logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")
    
    # 保存结果到文件
    if valid_links:
        with open("valid_links.txt", "w", encoding="utf-8") as f:
            for v in valid_links:
                f.write(v + "\n")
        logger.info("📄 结果已保存到 valid_links.txt")
    else:
        logger.warning("📄 无有效链接，不保存文件")
    
    # 发送到Telegram
    if BOT_TOKEN and CHANNEL_ID and valid_links:
        logger.info("\n📤 正在推送结果到Telegram...")
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
    elif valid_links:
        logger.warning("\n❌ 未设置BOT_TOKEN或CHANNEL_ID，跳过推送")
    
    logger.info("\n✅ 任务完成！")

if __name__ == "__main__":
    asyncio.run(main())
