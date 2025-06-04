import os
import re
import time
import asyncio
import logging
from urllib.parse import quote

import requests  # 用于订阅链接的验证
from telegram import Bot
from telegram.constants import ParseMode

# 从 requests-html 改为 AsyncHTMLSession
from requests_html import AsyncHTMLSession

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Telegram Bot 配置（从环境变量读取）
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

FREEFQ_URL = "https://freefq.com/free-ssr/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

async def extract_links_from_freefq():
    """
    使用 AsyncHTMLSession 渲染页面并提取 Clash/V2Ray/SSR/SS 链接
    """
    logger.info(f"🌐 正在爬取: {FREEFQ_URL}")

    try:
        asession = AsyncHTMLSession()
        # 发起异步 GET 请求
        r = await asession.get(FREEFQ_URL, headers={"User-Agent": USER_AGENT})

        # 渲染页面，等待 JS 执行
        await r.html.arender(timeout=20, sleep=2)

        text = r.html.full_text  # 渲染完成后获取完整文本
        links = set()

        # 提取所有 http(s)://... 格式的 URL
        url_pattern = re.compile(r'https?://[^\s\'"<>()]+')
        for match in url_pattern.findall(text):
            # 只保留可能的订阅链接
            if any(x in match for x in ['subscribe', 'clash', '.yaml', '.txt']):
                links.add(match.strip())

        # 提取 base64 编码格式的节点链接（ssr://、vmess://、trojan:// 等）
        base64_links = re.findall(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', text)
        links.update(base64_links)

        logger.info(f"🔗 提取到 {len(links)} 个可能订阅链接")
        return list(links)

    except Exception as e:
        logger.error(f"❌ 页面解析失败: {str(e)}")
        return []

def validate_subscription(url: str) -> bool:
    """
    同步函数：判断 URL 是否有效订阅链接
    """
    try:
        # 随机延迟避免同一时间请求过于集中
        time.sleep(1)

        # 规范化 URL
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"    ❌ HTTP {resp.status_code}: {url}")
            return False

        content = resp.text.lower()
        # 如果页面里包含常见的 VPN 配置关键词，视作有效
        if any(k in content for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless', 'clash']):
            logger.info(f"    ✔️ 有效订阅: {url}")
            return True

        # 如果整个返回是 Base64 字符串，也视作有效
        if re.fullmatch(r'[A-Za-z0-9+/=]+', content.strip()):
            logger.info(f"    ✔️ 有效Base64: {url}")
            return True

        logger.warning(f"    ❌ 无有效配置: {url}")
        return False

    except Exception as e:
        logger.warning(f"⚠️ 链接验证异常: {url} - {str(e)}")
        return False

async def send_to_telegram(bot_token: str, channel_id: str, urls: list):
    """
    将有效订阅链接通过 Telegram Bot 推送到指定频道/群组
    """
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    # 构建 HTML 格式消息
    text = "🌐 <b>FreeFQ 最新 VPN 节点订阅</b>\n\n"
    text += f"更新时间：<code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"

    # 只展示前 10 条
    for i, link in enumerate(urls[:10], 1):
        safe_url = quote(link, safe=":/?=&")
        snippet = link if len(link) <= 60 else (link[:57] + "...")
        text += f"{i}. <code>{snippet}</code>\n"
        text += f"   👉 <a href=\"{safe_url}\">点我使用</a>\n\n"

    text += "⚠️ 本链接仅供学习用途，请遵守当地法律法规"

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        logger.info("✅ 成功发送 Telegram 消息")
    except Exception as e:
        logger.error(f"❌ Telegram 推送失败: {str(e)}")

async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")

    # 1. 异步爬取并渲染页面，提取所有可能的订阅链接
    all_links = await extract_links_from_freefq()

    # 2. 同步验证每一个链接是否有效
    valid_links = []
    for link in all_links:
        if validate_subscription(link):
            valid_links.append(link)

    logger.info(f"✔️ 有效链接数量: {len(valid_links)}")

    # 3. 将有效链接写入文件（可选，方便后续检查）
    if valid_links:
        with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
            for link in valid_links:
                f.write(link + "\n")
        logger.info("📄 已保存到 freefq_valid_links.txt")

    # 4. 如果环境变量里有 BOT_TOKEN 和 CHANNEL_ID，则推送到 Telegram
    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
    else:
        logger.warning("❌ 未配置 BOT_TOKEN 或 CHANNEL_ID，已跳过推送")

if __name__ == "__main__":
    # 通过 asyncio.run 启动整个异步流程
    asyncio.run(main())
