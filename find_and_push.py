import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
from urllib.parse import urljoin, quote

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

BASE_URL = "https://nodefree.net"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}


def get_threads_on_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        threads = []
        for a_tag in soup.select("h2.entry-title > a[href]"):
            href = a_tag["href"]
            if href.startswith("/p/") and href.endswith(".html"):
                full_url = urljoin(BASE_URL, href)
                threads.append(full_url)

        return list(set(threads))
    except Exception as e:
        print(f"⚠️ 获取文章列表失败: {url}，错误: {e}")
        return []


def extract_yaml_links_from_thread(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"\.ya?ml$", href, re.I):
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = urljoin(BASE_URL, href)
                links.add(href)
        return list(links)
    except Exception as e:
        print(f"⚠️ 解析文章失败: {url}，错误: {e}")
        return []


def validate_subscription(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"❌ 失败 (HTTP {res.status_code}): {url}")
            return False
        text = res.text.lower()
        return any(keyword in text for keyword in ("proxies", "vmess://", "ss://", "clash"))
    except Exception as e:
        print(f"❌ 验证失败: {url}，错误: {e}")
        return False


async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        print("❌ 无有效链接，跳过推送")
        return

    text = "🆕 <b>最新 NodeFree 免费节点合集</b>\n\n"
    for i, url in enumerate(urls[:20], start=1):
        safe_url = quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a>\n\n"

    text = text[:3900]  # 规避 Telegram 消息长度限制

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        print("✅ 推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {e}")


async def main():
    print("🌐 开始爬取 nodefree.net 文章列表...")
    all_yaml_links = set()

    for page in range(1, 5):
        page_url = BASE_URL if page == 1 else f"{BASE_URL}/page/{page}"
        print(f"➡️ 抓取列表页: {page_url}")
        threads = get_threads_on_page(page_url)
        print(f"  发现 {len(threads)} 篇文章")

        for thread_url in threads:
            print(f"   ↪️ 解析文章: {thread_url}")
            yaml_links = extract_yaml_links_from_thread(thread_url)
            print(f"     找到 {len(yaml_links)} 个 YAML 链接")
            all_yaml_links.update(yaml_links)

    print(f"\n🔍 共 {len(all_yaml_links)} 个链接，开始验证")
    valid_links = [url for url in all_yaml_links if validate_subscription(url)]
    print(f"\n✔️ 有效链接数: {len(valid_links)}")

    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")

    print("📄 已保存到 valid_links.txt")

    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)


if __name__ == "__main__":
    asyncio.run(main())
