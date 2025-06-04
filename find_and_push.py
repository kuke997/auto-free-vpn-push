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
    url = f"{BASE_URL}/f/{page}" if page > 1 else BASE_URL
    print(f"🔍 正在爬取页面: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        
        # 使用BeautifulSoup解析HTML
        soup = BeautifulSoup(resp.text, 'html.parser')
        threads = []
        
        # 查找所有文章链接 - 根据当前网站结构
        for link in soup.select('a.list-group-item'):
            href = link.get('href')
            if href and href.startswith('/p/'):
                full_url = urljoin(BASE_URL, href)
                threads.append(full_url)
        
        print(f"✅ 找到 {len(threads)} 篇文章")
        return threads
    
    except Exception as e:
        print(f"⚠️ 获取页面失败 {url} 错误: {str(e)}")
        return []

def extract_yaml_links_from_thread(url):
    """
    从单个文章页面中提取所有订阅链接
    """
    print(f"📝 正在解析文章: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        
        # 使用BeautifulSoup解析HTML
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = set()
        
        # 提取所有可能的订阅链接
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # 匹配.yaml/.yml文件
            if re.search(r'\.ya?ml$', href, re.I):
                links.add(href)
            
            # 匹配.txt文件
            elif re.search(r'\.txt$', href, re.I):
                links.add(href)
            
            # 匹配常见订阅服务域名
            elif any(domain in href for domain in 
                    ['githubrowcontent', 'github.io', 'sub-store', 'subscribe', 'clash', 'v2ray']):
                links.add(href)
        
        # 检查文章内容中的直接链接
        content = soup.select_one('div.content')
        if content:
            text_links = re.findall(r'https?://[^\s"\']+', content.text)
            for link in text_links:
                if any(ext in link for ext in ['.yaml', '.yml', '.txt', 'sub-store', 'clash']):
                    links.add(link)
        
        print(f"   🔗 提取到 {len(links)} 个订阅链接")
        return list(links)
    
    except Exception as e:
        print(f"⚠️ 解析帖子失败 {url} 错误: {str(e)}")
        return []

def validate_subscription(url):
    """
    验证订阅链接是否有效
    """
    print(f"🔐 正在验证链接: {url}")
    
    try:
        # 添加随机延迟避免被封
        time.sleep(random.uniform(0.5, 1.5))
        
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print(f"    ❌ HTTP {res.status_code}: {url}")
            return False
        
        content = res.text
        # 检查常见VPN配置关键词
        if any(keyword in content.lower() for keyword in 
               ["proxies", "proxy-providers", "vmess", "ss://", "trojan", "vless", "clash"]):
            print(f"    ✔️ 有效订阅: {url}")
            return True
        
        print(f"    ❌ 无效订阅 (无VPN配置): {url}")
        return False
    
    except Exception as e:
        print(f"    ❌ 验证异常: {url}，错误: {str(e)}")
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    """
    将有效订阅链接推送到 Telegram 频道
    """
    if not urls:
        print("❌ 无有效链接，跳过推送")
        return
    
    # 创建消息内容
    text = "🆕 <b>NodeFree 最新免费VPN订阅合集</b>\n\n"
    text += "更新时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
    
    for i, u in enumerate(urls[:20], 1):
        safe = quote(u, safe=":/?=&")
        text += f"{i}. <a href=\"{safe}\">{u}</a>\n"
    
    text += "\n⚠️ 仅供学习使用，请遵守当地法律法规"
    
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
        print("✅ 推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {str(e)}")

async def main():
    print("="*50)
    print(f"🌐 NodeFree 免费节点爬虫启动 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    
    all_links = set()
    valid_links = []
    
    # 爬取前3页内容
    for page in range(1, 4):
        threads = get_threads_on_page(page)
        
        # 随机延迟避免请求过快
        time.sleep(random.uniform(1, 3))
        
        for t in threads:
            subs = extract_yaml_links_from_thread(t)
            all_links.update(subs)
            
            # 随机延迟避免请求过快
            time.sleep(random.uniform(0.5, 2))
    
    print(f"\n🔍 共提取到 {len(all_links)} 条订阅链接，开始验证...")
    
    for link in all_links:
        if validate_subscription(link):
            valid_links.append(link)
    
    print(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")
    
    # 保存结果到文件
    with open("valid_links.txt", "w", encoding="utf-8") as f:
        for v in valid_links:
            f.write(v + "\n")
    print("📄 结果已保存到 valid_links.txt")
    
    # 发送到Telegram
    if BOT_TOKEN and CHANNEL_ID:
        print("\n📤 正在推送结果到Telegram...")
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
    
    print("\n✅ 任务完成！")

if __name__ == "__main__":
    asyncio.run(main())
