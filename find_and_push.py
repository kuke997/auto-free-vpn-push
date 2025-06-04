import os
import re
import time
import asyncio
import logging
from urllib.parse import quote

import requests  # 验证订阅链接时同步请求用
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


# ---------------------- 配置常量 ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

FREEFQ_URL = "https://freefq.com/free-ssr/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ---------------------- 提取函数 ----------------------
async def extract_links_from_freefq():
    """
    使用 AsyncHTMLSession 渲染页面并从完整 HTML 源码中提取 Clash/V2Ray/SSR/SS/Vmess/Trojan 链接。
    """
    logger.info(f"🌐 正在爬取: {FREEFQ_URL}")

    asession = AsyncHTMLSession()
    try:
        # 1. 发起异步 GET 请求
        r = await asession.get(FREEFQ_URL, headers={"User-Agent": USER_AGENT})

        # 2. 渲染页面，等待 JS 执行完毕
        #    sleep=3 保证更多动态内容加载，timeout=30 给足够时间
        await r.html.arender(timeout=30, sleep=3)

        # 3. 从 r.html.html（完整 HTML）中做正则，抓取所有可能的订阅链接
        html_source = r.html.html  # 比 full_text 更包含隐藏的属性、标签内的链接

        links = set()

        # 3.1 提取所有 http(s)://... 格式的 URL
        url_pattern = re.compile(r'https?://[^\s\'"<>()]+')
        for match in url_pattern.findall(html_source):
            # 只保留含有订阅关键字或常见文件后缀的链接
            if any(k in match for k in ['subscribe', 'clash', '.yaml', '.txt']):
                links.add(match.strip())

        # 3.2 提取 Base64 格式的节点链接（ssr://、ss://、vmess://、trojan://）
        base64_pattern = re.compile(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+')
        for m in base64_pattern.findall(html_source):
            # re.findall 会返回 tuple，每次 m 是 ('ssr', '...')，实际整条协议链接在 html_source 中，需要用 finditer
            pass

        # 事实上，上面 re.findall 只返回协议类型，为了拿到整条链接，用 finditer：
        for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', html_source):
            links.add(m.group(0).strip())

        logger.info(f"🔗 提取到 {len(links)} 个可能订阅链接")
        return list(links)

    except Exception as e:
        logger.error(f"❌ 页面解析失败: {str(e)}")
        return []

    finally:
        # 4. 关闭 AsyncHTMLSession，释放 Chromium 进程，避免“Event loop is closed”警告
        try:
            await asession.close()
        except Exception:
            pass


# ---------------------- 验证函数 ----------------------
def validate_subscription(url: str) -> bool:
    """
    同步函数：判断 URL 是否有效订阅链接
    """
    try:
        # 随机延迟，以免被目标服务器短时间内刷出过多请求
        time.sleep(1)

        # 规范化 URL（支持 // 开头或省略 http）
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"    ❌ HTTP {resp.status_code}: {url}")
            return False

        content = resp.text.lower()
        # 如果页面中包含常见 VPN 配置关键词，则视为有效订阅
        if any(k in content for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless', 'clash']):
            logger.info(f"    ✔️ 有效订阅: {url}")
            return True

        # 如果整个返回体仅是 Base64 字符串，也当作有效订阅
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
    将有效订阅链接通过 Telegram Bot 推送到指定频道/群组
    """
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    # 拼接 HTML 格式消息
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


# ---------------------- 主流程 ----------------------
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
    asyncio.run(main())
