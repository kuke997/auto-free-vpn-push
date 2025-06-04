import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
import urllib.parse

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
    """
    从 nodefree.net 列表页抓取文章链接
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        threads = []
        # 文章链接一般是 <a href="/t/xxx-xxx/123" class="title">...</a> 或者 <h2 class="topic-title"> <a href=...>
        # 根据实际页面结构，调整选择器：
        for a in soup.select('a[href^="/t/"]'):
            href = a.get("href")
            if href and href.startswith("/t/"):
                full_url = BASE_URL + href
                threads.append(full_url)
        # 去重
        threads = list(set(threads))
        return threads
    except Exception as e:
        print(f"⚠️ 获取列表页文章失败：{url}，错误：{e}")
        return []

def extract_yaml_links_from_thread(url):
    """
    从单篇文章页抓取所有 .yaml 配置链接
    """
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
                    href = BASE_URL + href
                links.add(href)
        return list(links)
    except Exception as e:
        print(f"⚠️ 解析文章页面失败：{url}，错误：{e}")
        return []

def validate_subscription(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"    ❌ 验证失败（HTTP {res.status_code}）: {url}")
            return False
        text = res.text.lower()
        valid = any(k in text for k in ("proxies", "vmess://", "ss://", "clash"))
        print(f"    {'✔️ 有效' if valid else '❌ 无效'} 订阅链接: {url}")
        return valid
    except Exception as e:
        print(f"    ❌ 验证异常: {url}，错误: {e}")
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        print("❌ 没有可用节点，跳过推送")
        return

    text = "🆕 <b>2025年 nodefree.net 免费VPN订阅合集（Clash/V2Ray/SS）</b>\n\n"
    for i, url in enumerate(urls[:20], start=1):
        safe_url = urllib.parse.quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a>\n\n"

    if len(text.encode("utf-8")) > 4000:
        text = text.encode("utf-8")[:4000].decode("utf-8", errors="ignore") + "\n..."

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
        print("❌ Telegram 推送失败:", e)

async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("⚠️ 未设置 BOT_TOKEN 或 CHANNEL_ID，将跳过 Telegram 推送")

    print("🌐 开始爬取 nodefree.net 文章列表...")

    all_yaml_links = set()

    # 爬取首页 + 前3页（可根据需要调整）
    for page in range(1, 5):
        if page == 1:
            url = BASE_URL + "/"
        else:
            url = f"{BASE_URL}/page/{page}"
        print(f"➡️ 抓取列表页: {url}")
        threads = get_threads_on_page(url)
        print(f" 发现 {len(threads)} 篇文章")
        for thread_url in threads:
            print(f"   ↪️ 解析文章: {thread_url}")
            yaml_links = extract_yaml_links_from_thread(thread_url)
            print(f"      找到 {len(yaml_links)} 个 YAML 链接")
            all_yaml_links.update(yaml_links)

    print(f"\n🔍 验证订阅链接有效性，共 {len(all_yaml_links)} 个链接")
    valid_links = []
    for link in all_yaml_links:
        if validate_subscription(link):
            valid_links.append(link)

    print(f"\n✔️ 有效订阅链接数量: {len(valid_links)}")
    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
