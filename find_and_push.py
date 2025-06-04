import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
from urllib.parse import urljoin, quote

# 从环境变量读取 Telegram Bot Token 和频道 ID
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

BASE_URL = "https://nodefree.net"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}

def get_threads_via_rss():
    """
    通过 RSS（latest.rss）获取 nodefree.net 最近发布的帖子链接
    """
    rss_url = BASE_URL + "/latest.rss"
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        xml = resp.text
        # 用正则提取所有 <link>https://nodefree.net/p/数字.html</link>
        links = re.findall(r"<link>(https://nodefree\.net/p/\d+\.html)</link>", xml)
        # RSS 中第一个 <link> 通常是站点链接，items 在后面；strip 重复并返回唯一列表
        unique_links = []
        for link in links:
            if link not in unique_links:
                unique_links.append(link)
        print(f"✅ RSS 共提取到 {len(unique_links)} 条帖子链接")
        return unique_links
    except Exception as e:
        print(f"⚠️ 获取 RSS 失败: {e}")
        return []

def extract_yaml_links_from_thread(url):
    """
    访问单篇帖子页面，提取其中所有以 .yaml 或 .yml 结尾的链接
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"\.ya?ml$", href, re.I):
                # 补全相对链接
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = urljoin(BASE_URL, href)
                links.add(href)
        print(f"   📝 {url} 找到 {len(links)} 个 YAML 链接")
        return list(links)
    except Exception as e:
        print(f"⚠️ 解析帖子失败: {url}，错误: {e}")
        return []

def validate_subscription(url):
    """
    验证订阅链接内容是否包含常见配置关键词
    """
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"    ❌ HTTP {res.status_code}: {url}")
            return False
        text = res.text.lower()
        valid = any(k in text for k in ("proxies", "vmess://", "ss://", "clash"))
        print(f"    {'✔️ 有效' if valid else '❌ 无效'} 订阅链接: {url}")
        return valid
    except Exception as e:
        print(f"    ❌ 验证异常: {url}，错误: {e}")
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    """
    将有效链接通过 Telegram Bot 推送到指定频道／聊天
    """
    if not urls:
        print("❌ 无有效链接，跳过推送")
        return

    text = "🆕 <b>最新 NodeFree 免费VPN订阅合集</b>\n\n"
    for url in urls[:20]:
        safe_url = quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a>\n\n"

    # 确保不超过 Telegram 消息长度限制
    text = text[:3900]

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        print("✅ Telegram 推送成功")
    except Exception as e:
        print(f"❌ Telegram 推送失败: {e}")

async def main():
    # 一开始打印日志，帮助调试
    print("🌐 开始通过 RSS (latest.rss) 爬取 nodefree.net 文章列表…")

    # 1. 从 RSS 提取帖子链接
    threads = get_threads_via_rss()
    print(f"总共拿到 {len(threads)} 条帖子链接\n")

    # 2. 依次访问每条帖子并收集 .yaml 链接
    all_yaml_links = set()
    for thread_url in threads:
        yaml_links = extract_yaml_links_from_thread(thread_url)
        all_yaml_links.update(yaml_links)

    print(f"\n🔍 开始验证 {len(all_yaml_links)} 条可能的订阅链接…")
    valid_links = [u for u in all_yaml_links if validate_subscription(u)]
    print(f"\n✔️ 共 {len(valid_links)} 条有效订阅链接")

    # 3. 保存到 valid_links.txt
    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    # 4. 如果环境变量里配置了 BOT_TOKEN 和 CHANNEL_ID，就推送到 Telegram
    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
