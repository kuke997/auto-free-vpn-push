import os
import re
import time
import asyncio
import logging
from urllib.parse import quote

from telegram import Bot
from telegram.constants import ParseMode
from requests_html import HTMLSession

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# 配置环境变量（建议从 GitHub Secrets 注入）
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

FREEFQ_URL = "https://freefq.com/free-ssr/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

def extract_links_from_freefq():
    """
    使用 requests-html 渲染页面并提取 Clash/V2Ray/SSR/SS 链接
    """
    logger.info(f"🌐 正在爬取: {FREEFQ_URL}")
    try:
        session = HTMLSession()
        resp = session.get(FREEFQ_URL, headers={"User-Agent": USER_AGENT})
        resp.html.render(timeout=20, sleep=2)

        text = resp.html.full_text
        links = set()

        # 提取订阅链接
        url_pattern = re.compile(r'https?://[^\s\'"<>()]+')
        for match in url_pattern.findall(text):
            if any(x in match for x in ['subscribe', 'clash', '.yaml', '.txt']):
                links.add(match.strip())

        # 提取 base64 编码的节点链接
        base64_links = re.findall(r'(ssr|ss|vmess|trojan)://[a-zA-Z0-9+/=]+', text)
        links.update(base64_links)

        logger.info(f"🔗 提取到 {len(links)} 个可能订阅链接")
        return list(links)

    except Exception as e:
        logger.error(f"❌ 页面解析失败: {str(e)}")
        return []

def validate_subscription(url):
    """
    判断 URL 是否有效订阅链接
    """
    try:
        time.sleep(1)
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        import requests
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if res.status_code != 200:
            return False

        text = res.text.lower()
        if any(k in text for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless']):
            logger.info(f"✅ 有效订阅: {url}")
            return True
        if re.fullmatch(r'[A-Za-z0-9+/=]+', text.strip()):
            logger.info(f"✅ 有效Base64: {url}")
            return True
        return False
    except Exception as e:
        logger.warning(f"⚠️ 链接验证失败: {url} - {str(e)}")
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    text = "🌐 <b>FreeFQ 最新 VPN 节点订阅</b>\n\n"
    text += f"更新时间：<code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"

    for i, link in enumerate(urls[:10], 1):
        safe_url = quote(link, safe=":/?=&")
        text += f"{i}. <code>{link[:60]}...</code>\n"
        text += f"   👉 <a href=\"{safe_url}\">点我使用</a>\n\n"

    text += "⚠️ 本链接仅供学习用途，请遵守当地法律法规"

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        logger.info("✅ 成功发送 Telegram 消息")
    except Exception as e:
        logger.error(f"❌ Telegram 推送失败: {str(e)}")

async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")
    all_links = extract_links_from_freefq()
    valid_links = [link for link in all_links if validate_subscription(link)]

    logger.info(f"✔️ 有效链接数量: {len(valid_links)}")
    if valid_links:
        with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
            for link in valid_links:
                f.write(link + "\n")

    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
