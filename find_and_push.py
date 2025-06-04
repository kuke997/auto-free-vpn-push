import os
import re
import time
import asyncio
import logging
from urllib.parse import quote, urljoin

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

FREEFQ_CATEGORY_URL = "https://freefq.com/free-ssr/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ---------------------- 提取分类页文章链接 ----------------------
async def extract_post_urls(asession):
    """
    渲染分类页后，从 <a> 标签中提取所有 /free-ssr/xxx.html 格式的文章链接
    """
    try:
        r = await asession.get(FREEFQ_CATEGORY_URL, headers={"User-Agent": USER_AGENT})
        # sleep=2 给 JS 更多加载时间，timeout=30 以防网速慢
        await r.html.arender(timeout=30, sleep=2)

        post_urls = set()
        for a in r.html.find('a'):
            href = a.attrs.get('href', '').strip()
            # 只抓 /free-ssr/xxx.html 结尾的链接
            if href and '/free-ssr/' in href and href.endswith('.html'):
                # 处理相对链接
                full_url = href if href.startswith('http') else urljoin(FREEFQ_CATEGORY_URL, href)
                post_urls.add(full_url)
        logger.info(f"📰 在分类页共找到 {len(post_urls)} 篇文章")
        return list(post_urls)

    except Exception as e:
        logger.error(f"❌ 提取分类页文章链接失败: {str(e)}")
        return []


# ---------------------- 提取单篇文章中的订阅链接 ----------------------
async def extract_links_from_post(asession, post_url):
    """
    渲染单个文章页后，从 HTML 源码、<a>、<code>、<pre> 中提取所有可能的订阅链接
    """
    links = set()
    try:
        r = await asession.get(post_url, headers={"User-Agent": USER_AGENT})
        await r.html.arender(timeout=30, sleep=2)

        html_source = r.html.html or ""

        # 1. 从完整 HTML 源码用正则提取 http(s):// 格式的链接
        for match in re.findall(r'https?://[^\s\'"<>()]+', html_source):
            if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                links.add(match.strip())

        # 2. 再从源码里提取 base64 格式节点（ssr://、ss://、vmess://、trojan://）
        for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', html_source):
            links.add(m.group(0).strip())

        # 3. 单独遍历 <a> 标签，避免部分链接仅出现在 href 属性中
        for a in r.html.find('a'):
            href = a.attrs.get('href', '').strip()
            if href and any(k in href for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe', 'ssr://', 'vmess://']):
                full = href if href.startswith('http') else urljoin(post_url, href)
                links.add(full.strip())

        # 4. 遍历 <code> 和 <pre> 块里的文本，补充提取被 JS/脚本写入文本中的节点
        for block in r.html.find('code, pre'):
            text = block.text or ""
            # 4.1 Base64 格式
            for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', text):
                links.add(m.group(0).strip())
            # 4.2 http(s):// 格式
            for match in re.findall(r'https?://[^\s\'"<>()]+', text):
                if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                    links.add(match.strip())

        logger.info(f"   🔗 文章 {post_url} 提取到 {len(links)} 条链接")
        return list(links)

    except Exception as e:
        logger.error(f"❌ 提取文章 {post_url} 链接失败: {str(e)}")
        return []


# ---------------------- 验证订阅链接有效性 ----------------------
def validate_subscription(url: str) -> bool:
    """
    同步检验 URL 是否有效订阅链接：
      1. HTTP 状态码 200
      2. 页面或返回体包含常见关键词（proxies、vmess、ss://、trojan、vless、clash 等）
      3. 或者整条返回体是纯 Base64 字符串
    """
    try:
        time.sleep(1)  # 随机延迟，防止过快请求

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
        # 包含常见 VPN 字段即视为有效
        if any(k in content for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless', 'clash']):
            logger.info(f"    ✔️ 有效订阅: {url}")
            return True

        # 如果返回体本身就是纯 Base64 也当作有效
        if re.fullmatch(r'[A-Za-z0-9+/=]+', content.strip()):
            logger.info(f"    ✔️ 有效Base64: {url}")
            return True

        logger.warning(f"    ❌ 无有效配置: {url}")
        return False

    except Exception as e:
        logger.warning(f"⚠️ 验证异常: {url} - {str(e)}")
        return False


# ---------------------- 推送到 Telegram ----------------------
async def send_to_telegram(bot_token: str, channel_id: str, urls: list):
    """
    异步推送前 10 条有效链接到 Telegram 频道 / 群组
    """
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    text = "🌐 <b>FreeFQ 免费节点订阅（更新）</b>\n\n"
    text += f"更新时间：<code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"

    for i, link in enumerate(urls[:10], 1):
        safe = quote(link, safe=":/?=&")
        snippet = link if len(link) <= 60 else (link[:57] + "...")
        text += f"{i}. <code>{snippet}</code>\n"
        text += f"   👉 <a href=\"{safe}\">点我使用</a>\n\n"

    text += "⚠️ 仅供学习用途，请遵守当地法律法规"

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        logger.info("✅ Telegram 推送成功")
    except Exception as e:
        logger.error(f"❌ Telegram 推送失败: {str(e)}")


# ---------------------- 主流程 ----------------------
async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")
    asession = AsyncHTMLSession()
    try:
        # 1. 提取最新文章 URL 列表
        post_urls = await extract_post_urls(asession)

        # 2. 针对最新 N 篇（这里取 5）文章，提取订阅链接
        all_links = set()
        for post_url in sorted(post_urls, reverse=True)[:5]:
            links = await extract_links_from_post(asession, post_url)
            all_links.update(links)
        logger.info(f"\n🔍 共提取到 {len(all_links)} 条可能订阅链接，开始验证...")

        # 3. 同步验证有效订阅链接
        valid_links = []
        for link in all_links:
            if validate_subscription(link):
                valid_links.append(link)
        logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")

        # 4. 保存到本地文件，方便后续检查
        if valid_links:
            with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
                for v in valid_links:
                    f.write(v + "\n")
            logger.info("📄 已保存到 freefq_valid_links.txt")

        # 5. 推送到 Telegram（若配置了 BOT_TOKEN & CHANNEL_ID）
        if BOT_TOKEN and CHANNEL_ID:
            await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
        else:
            logger.warning("❌ 未配置 BOT_TOKEN 或 CHANNEL_ID，已跳过 Telegram 推送")

    finally:
        # 显式关闭 AsyncHTMLSession，避免 “Event loop is closed” 报错
        try:
            await asession.close()
            logger.info("ℹ️ AsyncHTMLSession 已关闭")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
