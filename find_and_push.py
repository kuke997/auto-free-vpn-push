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

        for article in soup.select('div.topic-list-item'):
            title_link = article.select_one('a.title')
            if title_link:
                href = title_link.get('href')
                if href:
                    full_url = urljoin(BASE_URL, href)
                    threads.append(full_url)
        
        logger.info(f"✅ 找到 {len(threads)} 篇文章")
        return threads
    except Exception as e:
        logger.error(f"⚠️ 获取页面失败 {url} 错误: {str(e)}")
        return []

def extract_subscription_links(url):
    logger.info(f"📝 正在解析文章: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if any(pattern in href for pattern in ['.yaml', '.yml', '.txt', 'clash', 'v2ray', 'subscribe', 'nodefree']):
                if not href.startswith('http'):
                    href = urljoin(url, href)
                links.add(href)

        content = soup.select_one('div.content') or soup.select_one('div.post-content')
        if content:
            potential_links = re.findall(r'https?://[^\s"\']+', content.text)
            for link in potential_links:
                if any(pattern in link for pattern in ['.yaml', '.yml', '.txt', 'clash', 'v2ray', 'subscribe', 'nodefree']):
                    links.add(link)

        for code_block in soup.select('pre, code'):
            base64_links = re.findall(r'(?:ss|ssr|vmess|trojan)://[a-zA-Z0-9+/]+={0,2}', code_block.text)
            links.update(base64_links)
            text_links = re.findall(r'https?://[^\s"\']+', code_block.text)
            for link in text_links:
                if any(pattern in link for pattern in ['.yaml', '.yml', '.txt', 'clash', 'v2ray', 'subscribe']):
                    links.add(link)

        logger.info(f"   🔗 提取到 {len(links)} 个订阅链接")
        return list(links)
    except Exception as e:
        logger.error(f"⚠️ 解析帖子失败 {url} 错误: {str(e)}")
        return []

def validate_subscription(url):
    logger.info(f"🔐 正在验证链接: {url}")
    
    try:
        time.sleep(random.uniform(0.5, 1.5))
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url
            
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            logger.warning(f"    ❌ HTTP {res.status_code}: {url}")
            return False
        
        content = res.text
        vpn_keywords = ["proxies", "proxy-providers", "vmess", "ss://", "trojan", "vless", "clash", "port:"]
        for keyword in vpn_keywords:
            if keyword.lower() in content.lower():
                logger.info(f"    ✔️ 有效订阅: {url}")
                return True

        if re.search(r'^[A-Za-z0-9+/]+={0,2}$', content.strip()):
            logger.info(f"    ✔️ 有效订阅 (Base64编码): {url}")
            return True

        logger.warning(f"    ❌ 无效订阅 (无VPN配置): {url}")
        return False
    except Exception as e:
        logger.error(f"    ❌ 验证异常: {url}，错误: {str(e)}")
        return False

def get_freenodes_links():
    url = "https://freenodes.github.io/freenodes/"
    logger.info(f"🌐 正在爬取 Freenodes 页面: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = set()

        for a in soup.find_all("a", href=True):
            href = a['href']
            if any(ext in href for ext in ['.yaml', '.yml', '.txt', 'subscribe', 'clash']):
                full_url = urljoin(url, href)
                links.add(full_url)
            if any(proto in href for proto in ['ss://', 'vmess://', 'trojan://']):
                links.add(href)

        logger.info(f"   🔗 Freenodes 提取到 {len(links)} 个订阅链接")
        return list(links)
    except Exception as e:
        logger.error(f"⚠️ Freenodes 页面解析失败: {str(e)}")
        return []

async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return
    
    text = "🆕 <b>最新免费VPN订阅链接</b>\n\n"
    text += "更新时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
    text += "以下是可直接导入VPN客户端的订阅链接：\n\n"
    
    for i, u in enumerate(urls[:10], 1):
        safe = quote(u, safe=":/?=&")
        display_name = u.split('/')[-1] if '/' in u else u
        text += f"{i}. <code>{display_name}</code>\n"
        text += f"   <a href=\"{safe}\">点击复制订阅链接</a>\n\n"
    
    text += "⚠️ 仅供学习使用，请遵守当地法律法规\n"
    text += "🔒 订阅链接有效期通常为1-7天"

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
    logger.info(f"🌐 NodeFree + Freenodes 爬虫启动 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
    
    all_links = set()
    valid_links = []

    freenodes_links = get_freenodes_links()
    all_links.update(freenodes_links)
    time.sleep(random.uniform(1, 2))
    
    for page in range(1, 3):
        threads = get_threads_on_page(page)
        if not threads:
            logger.warning(f"⚠️ 第 {page} 页未找到文章，跳过")
            continue
        time.sleep(random.uniform(1, 3))
        for t in threads:
            subs = extract_subscription_links(t)
            all_links.update(subs)
            time.sleep(random.uniform(0.5, 2))
    
    logger.info(f"\n🔍 共提取到 {len(all_links)} 条订阅链接，开始验证...")
    
    for link in all_links:
        if validate_subscription(link):
            valid_links.append(link)
    
    logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")
    
    if valid_links:
        with open("valid_links.txt", "w", encoding="utf-8") as f:
            for v in valid_links:
                f.write(v + "\n")
        logger.info("📄 结果已保存到 valid_links.txt")
    else:
        logger.warning("📄 无有效链接，不保存文件")

    if BOT_TOKEN and CHANNEL_ID and valid_links:
        logger.info("\n📤 正在推送结果到Telegram...")
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
    elif valid_links:
        logger.warning("\n❌ 未设置BOT_TOKEN或CHANNEL_ID，跳过推送")

    logger.info("\n✅ 任务完成！")

if __name__ == "__main__":
    asyncio.run(main())
