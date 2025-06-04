import os
import re
import time
import asyncio
import logging
from urllib.parse import quote

import requests
from telegram import Bot
from telegram.constants import ParseMode

from requests_html import AsyncHTMLSession

# ---------------------- 日志配置 ----------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ---------------------- 环境变量 & 常量 ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

FREEFQ_URL = "https://freefq.com/free-ssr/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ---------------------- 提取函数 ----------------------
async def extract_links_from_freefq():
    """
    使用 AsyncHTMLSession 渲染页面后，全面从 HTML 源码、<a>、<code>、<pre> 中提取订阅链接。
    """
    logger.info(f"🌐 正在爬取: {FREEFQ_URL}")

    asession = AsyncHTMLSession()
    links = set()
    try:
        # 1. 异步 GET 并渲染页面
        r = await asession.get(FREEFQ_URL, headers={"User-Agent": USER_AGENT})
        await r.html.arender(timeout=30, sleep=3)

        # 2. 从完整 HTML 源码里做正则，提取 http(s)://xxx，以及 base64 节点链接
        html_source = r.html.html or ""
        # 2.1 提取所有 http(s)://... 格式的 URL
        url_pattern = re.compile(r'https?://[^\s\'"<>()]+')
        for match in url_pattern.findall(html_source):
            if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                links.add(match.strip())

        # 2.2 提取所有 base64 格式的节点链接（ssr://、ss://、vmess://、trojan://）
        for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', html_source):
            links.add(m.group(0).strip())

        # 3. 针对 <a> 标签再做一次提取（有些链接存在 href 属性但不在源码文本中）
        for a in r.html.find('a'):
            href = a.attrs.get('href', '')
            if href and any(k in href for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe', 'ssr://', 'vmess://']):
                # 处理相对 URL
                if href.startswith('//'):
                    href = 'https:' + href
                elif href.startswith('/'):
                    href = FREEFQ_URL.rstrip('/') + href
                links.add(href.strip())

        # 4. 针对 <code> 和 <pre> 标签里面的文本再做一次提取，防止部分节点被 JS 以文本形式插入
        for block in r.html.find('code, pre'):
            text = block.text or ""
            # 4.1 从文本中提取 base64 节点链接
            for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', text):
                links.add(m.group(0).strip())
            # 4.2 从文本中提取 http(s):// 格式的订阅链接
            for match in url_pattern.findall(text):
                if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                    links.add(match.strip())

        logger.info(f"🔗 提取到 {len(links)} 个可能订阅链接")
        return list(links)

    except Exception as e:
        logger.error(f"❌ 页面解析失败: {str(e)}")
        return []

    finally:
        # 5. 显式关闭 AsyncHTMLSession，避免脚本退出时 Chromium 进程未能正确关闭，导致 “Event loop is closed” 警告
        try:
            await asession.close()
            logger.info("ℹ️ AsyncHTMLSession 已关闭")
        except Exception:
            pass


# ---------------------- 验证函数 ----------------------
def validate_subscription(url: str) -> bool:
    """
    同步函数：检查 URL 是否有效订阅链接（HTTP 200 + 包含常见关键词，或仅为 Base64 字符串）。
    """
    try:
        time.sleep(1)  # 随机延迟，避免短时间过多请求

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
        # 如果页面内容包含常见 VPN 配置关键词，则判为有效
        if any(k in content for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless', 'clash']):
            logger.info(f"    ✔️ 有效订阅: {url}")
            return True

        # 如果返回体本身就是纯 Base64 字符串，也算有效
        if re.fullmatch(r'[A-Za-z0-9+/=]+', content.strip()):
            logger.info(f"    ✔️ 有效Base64: {url}")
            return True

        logger.warning(f"    ❌ 无有效配置: {url}")
        return False

    except Exception as e:
        logger.warning(f"⚠️ 链接验证异常: {url} - {str(e)}")
        return False


# ---------------------- 推送函数 ----------------------
async def send_to_telegram(bot_token: str, channel_id: str, urls: list):
    """
    将前十条有效订阅链接通过 Telegram Bot 推送到指定频道/群组（HTML 格式）。
    """
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    # 拼接 HTML 消息
    text = "🌐 <b>FreeFQ 最新 VPN 节点订阅</b>\n\n"
    text += f"更新时间：<code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"

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


# ---------------------- 主流程 ----------------------
async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")

    # 1. 异步爬取并渲染页面，提取所有可能的订阅链接
    all_links = await extract_links_from_freefq()

    # 2. 同步验证每个链接是否有效
    valid_links = []
    for link in all_links:
        if validate_subscription(link):
            valid_links.append(link)

    logger.info(f"✔️ 有效链接数量: {len(valid_links)}")

    # 3. 保存结果到本地文件，方便后续检查
    if valid_links:
        with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
            for l in valid_links:
                f.write(l + "\n")
        logger.info("📄 已保存到 freefq_valid_links.txt")

    # 4. 如果配置了 BOT_TOKEN 与 CHANNEL_ID，则推送到 Telegram
    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
    else:
        logger.warning("❌ 未配置 BOT_TOKEN 或 CHANNEL_ID，跳过 Telegram 推送")


if __name__ == "__main__":
    asyncio.run(main())
