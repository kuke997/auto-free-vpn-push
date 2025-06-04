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
    """
    只保留以下两类链接：
      1. 协议类：以 ssr://、ss://、vmess://、trojan:// 开头
      2. 文件后缀类：以 .yaml、.yml、.txt、.json 结尾（可带 ? 查询参数）
    """
    link = link.strip()
    # 协议类
    if re.match(r'^(ssr|ss|vmess|trojan)://', link):
        return True
    # 文件后缀类（后面可以有 ?query）
    if re.search(r'\.(yaml|yml|txt|json)(?:\?[^ ]*)?$', link):
        return True
    return False


# ---------------------- 提取分类页文章链接 ----------------------
async def extract_post_urls(asession):
    """
    渲染分类页后，从 r.html.html 里精准匹配 “/free-ssr/YYYY/MM/DD/xxx.html” 格式的文章链接，
    排除掉 index_*.html 这些分页/索引页。
    """
    try:
        r = await asession.get(FREEFQ_CATEGORY_URL, headers={"User-Agent": USER_AGENT})
        # 给 JS 足够时间加载
        await r.html.arender(timeout=30, sleep=2)

        html_source = r.html.html or ""
        post_urls = set()

        # 正则匹配：https://freefq.com/free-ssr/2025/06/03/ssr.html 这种格式
        pattern = re.compile(r'https?://freefq\.com/free-ssr/\d{4}/\d{2}/\d{2}/[^\'"<> ]+\.html')
        for m in pattern.finditer(html_source):
            post_urls.add(m.group(0).strip())

        logger.info(f"📰 在分类页共匹配到 {len(post_urls)} 篇真实文章")
        return list(post_urls)

    except Exception as e:
        logger.error(f"❌ 提取分类页文章链接失败: {str(e)}")
        return []


# ---------------------- 提取单篇文章中的“候选链接” ----------------------
async def extract_raw_links_from_post(asession, post_url):
    """
    渲染单条“文章页”，从：
      1. 完整 HTML 源码
      2. <a> 标签的 href
      3. <code> / <pre> 标签里的纯文本
    中提取所有“带有 clash/v2ray/.yaml/vmess:// 等关键词”的原始候选链接，
    但此处不做最终验证，只是先收集所有可能的 URL 或 Base64 协议串。
    """
    raw_links = set()
    try:
        r = await asession.get(post_url, headers={"User-Agent": USER_AGENT})
        # 渲染页面，等待 JS 执行
        await r.html.arender(timeout=30, sleep=2)

        html_source = r.html.html or ""

        # 1. 从完整 HTML 源码用正则提取所有 http(s)://… 格式的 URL
        for match in re.findall(r'https?://[^\s\'"<>()]+', html_source):
            # 只要链接里含“clash”、“v2ray”、“.yaml”、“.txt”、“subscribe”等关键词，就先收集
            if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                raw_links.add(match.strip())

        # 2. 从源码中提取 Base64 节点协议（ssr://、ss://、vmess://、trojan://）
        for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', html_source):
            raw_links.add(m.group(0).strip())

        # 3. 单独遍历 <a> 标签的 href 属性，避免某些链接只存在于属性值中而不在文本里
        for a in r.html.find('a'):
            href = a.attrs.get('href', '').strip()
            if href and any(k in href for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe', 'ssr://', 'vmess://']):
                full = href if href.startswith('http') else urljoin(post_url, href)
                raw_links.add(full.strip())

        # 4. 遍历 <code> 和 <pre> 标签内的文本，有时节点链接以纯文本形式插入
        for block in r.html.find('code, pre'):
            text = block.text or ""
            # 4.1 提取 Base64 格式协议
            for m in re.finditer(r'(ssr|ss|vmess|trojan)://[A-Za-z0-9+/=]+', text):
                raw_links.add(m.group(0).strip())
            # 4.2 提取 http(s)://… 格式
            for match in re.findall(r'https?://[^\s\'"<>()]+', text):
                if any(k in match for k in ['clash', 'v2ray', '.yaml', '.txt', 'subscribe']):
                    raw_links.add(match.strip())

        logger.info(f"   🔗 文章 {post_url} 共收集到 {len(raw_links)} 条“候选”链接")
        return list(raw_links)

    except Exception as e:
        logger.error(f"❌ 提取文章 {post_url} 候选链接失败: {str(e)}")
        return []


# ---------------------- 验证并筛选出“真实有效订阅链接” ----------------------
def filter_and_validate_links(raw_links):
    """
    1. 先用 is_subscription_link() 筛选“形式上像订阅”的URL
    2. 再用 requests.get 验证 HTTP 状态码 = 200，且内容中含“proxies/vmess/ss:///trojan/vless/clash”等关键词，
       或者返回体本身就是纯 Base64。
    返回最终“有效可用”的订阅链接列表。
    """
    filtered = []
    for link in raw_links:
        if not is_subscription_link(link):
            continue

        # 规范化 URL，方便后续请求
        url = link
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            url = 'https://' + url

        try:
            time.sleep(1)  # 随机延迟
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


# ---------------------- 异步推送到 Telegram ----------------------
async def send_to_telegram(bot_token: str, channel_id: str, urls: list):
    """
    将前 10 条有效订阅 URL 以 HTML 格式异步推送至 Telegram 频道/群组。
    """
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


# ---------------------- 主流程 ----------------------
async def main():
    logger.info("🚀 FreeFQ 节点爬虫启动")
    asession = AsyncHTMLSession()
    try:
        # 1. 从分类页提取所有“真实文章”链接
        post_urls = await extract_post_urls(asession)

        # 2. 针对最新 5 篇文章（可根据需求增减），收集它们所有的“候选原始链接”
        all_raw_links = set()
        for post_url in sorted(post_urls, reverse=True)[:5]:
            raw = await extract_raw_links_from_post(asession, post_url)
            all_raw_links.update(raw)
        logger.info(f"\n🔍 共收集到 {len(all_raw_links)} 条“候选”链接，开始筛选与验证…")

        # 3. 筛选并验证“真正的有效订阅链接”
        valid_links = filter_and_validate_links(list(all_raw_links))
        logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")

        # 4. 保存到本地文件（可选）
        if valid_links:
            with open("freefq_valid_links.txt", "w", encoding="utf-8") as f:
                for v in valid_links:
                    f.write(v + "\n")
            logger.info("📄 已保存到 freefq_valid_links.txt")

        # 5. 如果配置了 BOT_TOKEN & CHANNEL_ID，则异步推送到 Telegram
        if BOT_TOKEN and CHANNEL_ID:
            await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)
        else:
            logger.warning("❌ 未配置 BOT_TOKEN 或 CHANNEL_ID，跳过 Telegram 推送")

    finally:
        # 6. 显式关闭 AsyncHTMLSession，避免“Event loop is closed”报错
        try:
            await asession.close()
            logger.info("ℹ️ AsyncHTMLSession 已关闭")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
