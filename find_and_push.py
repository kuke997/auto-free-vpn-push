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


# ---------------------- 辅助：判断是否为“真实订阅链接” ----------------------
def is_subscription_link(link: str) -> bool:
    """
    只保留以下两类链接：
      1. 以 ssr://、ss://、vmess://、trojan:// 协议开头
      2. 以 .yaml、.yml、.txt、.json 等文件后缀结尾（后面可以带 ? 参数）
    """
    link = link.strip()
    # 协议协议类
    if re.match(r'^(ssr|ss|vmess|trojan)://', link):
        return True
    # 文件后缀类（后面可以带查询参数 ?）
    if re.search(r'\.(yaml|yml|txt|json)(?:\?[^ ]*)?$', link):
        return True
    return False


# ---------------------- 提取分类页文章链接 ----------------------
async def extract_post_urls(asession):
    """
    渲染分类页后，提取所有 /free-ssr/xxx.html 格式的文章 URL
    """
    try:
        r = await asession.get(FREEFQ_CATEGORY_URL, headers={"User-Agent": USER_AGENT})
        await r.html.arender(timeout=30, sleep=2)

        post_urls = set()
        for a in r.html.find('a'):
            href = a.attrs.get('href', '').strip()
            # 只抓 /free-ssr/xxx.html 结尾的链接
            if href and '/free-ssr/' in href and href.endswith('.html'):
                full_url = href if href.startswith('http') else urljoin(FREEFQ_CATEGORY_URL, href)
                post_urls.add(full_url)
        logger.info(f"📰 分类页共找到 {len(post_urls)} 篇文章")
        return list(post_urls)

    except Exception as e:
        logger.error(f"❌ 提取分类页文章链接失败: {str(e)}")
        return []


# ---------------------- 提取单篇文章中的“原始候选链接” ----------------------
async def extract_raw_links_from_post(asession, post_url):
    """
    渲染文章页后，从 HTML 源码、<a>、<code>、<pre> 中提取所有“候选订阅链接”，
    但不做最终过滤，只是把所有可能含订阅信息的 URL/B64 都收集起来。
    """
    raw_links = set()
    try:
        r = await asession.get(post_url, headers={"User-Agent": USER_AGENT})
        await r.html.arender(timeout=30, sleep=2)

        html_source = r.html.html or ""

        # 1. 从完整 HTML 源码中提取所有 http(s)://... 格式
        for match in re.findall(r'https?://[^\s\'"<>()]+', html_source):
            # 只要链接里含 “clash/v2ray/.yaml/.txt/subscribe” 就先收集
            if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                raw_links.add(match.strip())

        # 2. 从源码中提取 Base64 节点协议（ssr://、ss://、vmess://、trojan://）
        for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', html_source):
            raw_links.add(m.group(0).strip())

        # 3. 遍历 <a> 标签的 href 属性
        for a in r.html.find('a'):
            href = a.attrs.get('href', '').strip()
            if href and any(k in href for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe', 'ssr://', 'vmess://']):
                full = href if href.startswith('http') else urljoin(post_url, href)
                raw_links.add(full.strip())

        # 4. 遍历 <code> 和 <pre> 中的文本内容
        for block in r.html.find('code, pre'):
            text = block.text or ""
            # 4.1 提取 Base64 格式
            for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', text):
                raw_links.add(m.group(0).strip())
            # 4.2 提取 http(s):// 格式
            for match in re.findall(r'https?://[^\s\'"<>()]+', text):
                if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                    raw_links.add(match.strip())

        logger.info(f"   🔗 文章 {post_url} 共收集到 {len(raw_links)} 条候选链接")
        return list(raw_links)

    except Exception as e:
        logger.error(f"❌ 提取文章 {post_url} 候选链接失败: {str(e)}")
        return []


# ---------------------- 验证与筛选“真实订阅链接” ----------------------
def filter_and_validate_links(raw_links):
    """
    1. 先筛选 is_subscription_link()==True 的链接
    2. 再用 HTTP/内容检查，留下真正有效的订阅
    """
    filtered = []
    for link in raw_links:
        if not is_subscription_link(link):
            continue
        # 规范化一下，方便后面请求时不报错
        url = link
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        # 验证 HTTP 状态码和内容
        try:
            time.sleep(1)
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"    ❌ HTTP {resp.status_code}: {url}")
                continue

            content = resp.text.lower()
            if any(k in content for k in ['proxies', 'vmess', 'ss://', 'trojan', 'vless', 'clash']):
                logger.info(f"    ✔️ 有效订阅: {url}")
                filtered.append(url)
            elif re.fullmatch(r'[A-Za-z0-9+/=]+', content.strip()):
                logger.info(f"    ✔️ 有效Base64: {url}")
                filtered.append(url)
            else:
                logger.warning(f"    ❌ 无有效配置: {url}")

        except Exception as e:
            logger.warning(f"⚠️ 验证异常: {url} - {str(e)}")

    return filtered


# ---------------------- 推送到 Telegram ----------------------
async def send_to_telegram(bot_token: str, channel_id: str, urls: list):
    """
    异步推送前 10 条有效链接到 Telegram 频道/群组
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
        # 1. 获取分类页最新文章列表
        post_urls = await extract_post_urls(asession)

        # 2. 针对最新 5 篇（可根据需求调整）文章，收集“原始候选链接”
        all_raw_links = set()
        for post_url in sorted(post_urls, reverse=True)[:5]:
            raw = await extract_raw_links_from_post(asession, post_url)
            all_raw_links.update(raw)

        logger.info(f"\n🔍 共收集到 {len(all_raw_links)} 条“候选链接”，开始筛选与验证…")

        # 3. 筛选并验证最终有效订阅链接
        valid_links = filter_and_validate_links(list(all_raw_links))
        logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")

        # 4. 保存到本地文件（可选）
        if valid_links:
            with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
                for v in valid_links:
                    f.write(v + "\n")
            logger.info("📄 已保存到 freefq_valid_links.txt")

        # 5. 如果配置了 BOT_TOKEN & CHANNEL_ID，则推送到 Telegram
        if BOT_TOKEN and CHANNEL_ID:
            await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
        else:
            logger.warning("❌ 未配置 BOT_TOKEN 或 CHANNEL_ID，已跳过 Telegram 推送")

    finally:
        # 6. 关闭 AsyncHTMLSession，避免“Event loop is closed”报错
        try:
            await asession.close()
            logger.info("ℹ️ AsyncHTMLSession 已关闭")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
