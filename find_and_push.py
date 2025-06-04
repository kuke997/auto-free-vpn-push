import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
from urllib.parse import quote
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
BASE_URL = "https://freefq.com/free-ssr/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html",
}

def extract_links_from_freefq():
    """
    爬取 https://freefq.com/free-ssr/ 并提取订阅链接
    """
    logger.info(f"🌐 正在爬取: {BASE_URL}")
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        content_div = soup.find("div", class_="post-content") or soup.find("article")

        raw_text = content_div.get_text(separator="\n") if content_div else resp.text
        links = set()

        # 提取常规链接
        for match in re.findall(r'https?://[^\s\'"<>()]+', raw_text):
            if any(k in match for k in ['clash', 'v2ray', 'subscribe', '.yaml', '.txt']):
                links.add(match)

        # 提取 base64 编码配置链接
        for match in re.findall(r'(ssr|ss|vmess|trojan)://[a-zA-Z0-9+/=]+', raw_text):
            links.add(match)

        logger.info(f"🔗 提取到 {len(links)} 个可能订阅链接")
        return list(links)

    except Exception as e:
        logger.error(f"❌ 页面解析失败: {str(e)}")
        return []

def validate_subscription(url):
    logger.info(f"🔐 正在验证链接: {url}")
    try:
        time.sleep(random.uniform(0.5, 1.2))
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return False
        content = res.text
        if any(k in content.lower() for k in ["proxies", "vmess", "ss://", "trojan", "vless", "clash"]):
            logger.info(f"    ✔️ 有效链接: {url}")
            return True
        if re.match(r'^[A-Za-z0-9+/=]+$', content.strip()):
            logger.info(f"    ✔️ 有效Base64: {url}")
            return True
        return False
    except Exception as e:
        logger.warning(f"❌ 验证失败: {url} - {str(e)}")
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return
    text = "🆕 <b>FreeFQ 最新VPN订阅更新</b>\n\n"
    text += "更新时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"

    for i, u in enumerate(urls[:10], 1):
        safe = quote(u, safe=":/?=&")
        text += f"{i}. <code>{u[:60]}...</code>\n"
        text += f"   <a href=\"{safe}\">点击复制订阅链接</a>\n\n"

    text += "⚠️ 请遵守当地法律，仅供学习使用\n🔒 链接有效期通常为1-7天"

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        logger.info("✅ Telegram 推送成功")
    except Exception as e:
        logger.error(f"❌ Telegram 推送失败: {str(e)}")

async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")
    all_links = extract_links_from_freefq()
    valid_links = []

    for link in all_links:
        if validate_subscription(link):
            valid_links.append(link)

    logger.info(f"✔️ 有效链接数量: {len(valid_links)}")
    if valid_links:
        with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
            for l in valid_links:
                f.write(l + "\n")

    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
