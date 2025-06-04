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


# ---------------------- 帮助函数：判断“是否真的是订阅链接” ----------------------
def is_subscription_link(link: str) -> bool:
    link = link.strip()
    if re.match(r'^(ssr|ss|vmess|trojan)://', link):
        return True
    if re.search(r'\.(yaml|yml|txt|json)(?:\?[^ ]*)?$', link):
        return True
    return False


# ---------------------- 提取分类页文章链接 ----------------------
async def extract_post_urls(asession):
    try:
        r = await asession.get(FREEFQ_CATEGORY_URL, headers={"User-Agent": USER_AGENT})
        await r.html.arender(timeout=30, sleep=2)
        html_source = r.html.html or ""
        post_urls = set()

        # ✅ 更新后的正则：支持 /2025/06/03/*.html
        pattern = re.compile(r'https?://freefq\.com(?:/[^/]+)?/\d{4}/\d{2}/\d{2}/[^\'"<> ]+\.html')
        for m in pattern.finditer(html_source):
            post_urls.add(m.group(0).strip())

        logger.info(f"📰 在分类页共匹配到 {len(post_urls)} 篇真实文章")
        return list(post_urls)

    except Exception as e:
        logger.error(f"❌ 提取分类页文章链接失败: {str(e)}")
        return []


# ---------------------- 提取文章中的“候选链接” ----------------------
async def extract_raw_links_from_post(asession, post_url):
    raw_links = set()
    try:
        r = await asession.get(post_url, headers={"User-Agent": USER_AGENT})
        await r.html.arender(timeout=30, sleep=2)
        html_source = r.html.html or ""

        # 1. 从 HTML 中提取 http(s):// 链接
        for match in re.findall(r'https?://[^\s\'"<>()]+', html_source):
            if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                raw_links.add(match.strip())

        # 2. Base64 协议串
        for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', html_source):
            raw_links.add(m.group(0).strip())

        # 3. 提取 <a> 标签 href
        for a in r.html.find('a'):
            href = a.attrs.get('href', '').strip()
            if href and any(k in href for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe', 'ssr://', 'vmess://']):
                full = href if href.startswith('http') else urljoin(post_url, href)
                raw_links.add(full.strip())

        # 4. 提取 <code> / <pre> 中的文本
        for block in r.html.find('code, pre'):
            text = block.text or ""
            for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', text):
                raw_links.add(m.group(0).strip())
            for match in re.findall(r'https?://[^\s\'"<>()]+', text):
                if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                    raw_links.add(match.strip())

        logger.info(f"   🔗 文章 {post_url} 共收集到 {len(raw_links)} 条“候选”链接")
        return list(raw_links)

    except Exception as e:
        logger.error(f"❌ 提取文章 {post_url} 候选链接失败: {str(e)}")
        return []


# ---------------------- 验证并筛选出有效订阅链接 ----------------------
def filter_and_validate_links(raw_links):
    filtered = []
    for link in raw_links:
        if not is_subscription_link(link):
            continue
        url = link
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        try:
            time.sleep(1)
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"    ❌ HTTP {resp.status_code}: {url}")
                continue

            text = resp.text.lower()
            if any(k in text for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless', 'clash']):
                logger.info(f"    ✔️ 有效订阅: {url}")
                filtered.append(url)
            elif re.fullmatch(r'[A-Za-z0-9+/=]+', text.strip()):
                logger.info(f"    ✔️ 有效Base64: {url}")
                filtered.append(url)
            else:
                logger.warning(f"    ❌ 无有效配置: {url}")
        except Exception as e:
            logger.warning(f"⚠️ 验证异常: {url} - {str(e)}")
    return filtered


# ---------------------- 异步推送至 Telegram ----------------------
async def send_to_telegram(bot_token: str, channel_id: str, urls: list):
    if not urls:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    text = "🌐 <b>FreeFQ 最新免费节点订阅</b>\n\n"
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


# ---------------------- 主函数入口 ----------------------
async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")
    asession = AsyncHTMLSession()
    try:
        post_urls = await extract_post_urls(asession)
        all_raw_links = set()
        for post_url in sorted(post_urls, reverse=True)[:5]:
            raw = await extract_raw_links_from_post(asession, post_url)
            all_raw_links.update(raw)
        logger.info(f"\n🔍 共收集到 {len(all_raw_links)} 条“候选”链接，开始筛选与验证…")

        valid_links = filter_and_validate_links(list(all_raw_links))
        logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")

        if valid_links:
            with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
                for v in valid_links:
                    f.write(v + "\n")
            logger.info("📄 已保存到 freefq_valid_links.txt")

        if BOT_TOKEN and CHANNEL_ID:
            await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
        else:
            logger.warning("❌ 未配置 BOT_TOKEN 或 CHANNEL_ID，跳过 Telegram 推送")

    finally:
        try:
            await asession.close()
            logger.info("ℹ️ AsyncHTMLSession 已关闭")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
