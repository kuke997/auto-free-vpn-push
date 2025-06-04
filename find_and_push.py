import os
import re
import asyncio
import requests
from telegram import Bot
from telegram.constants import ParseMode
import urllib.parse

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

BASE_URL = "https://nodefree.net"
FIRST_PAGE_API = f"{BASE_URL}/latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}

def get_threads_with_pagination():
    """
    通过 Discourse API 递归获取所有主题，直到没有下一页
    """
    threads = []
    next_url = FIRST_PAGE_API

    while next_url:
        print(f"➡️ 抓取 API 页面: {next_url}")
        try:
            resp = requests.get(next_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            topics = data.get("topic_list", {}).get("topics", [])
            print(f"  抓取到 {len(topics)} 个主题")
            for topic in topics:
                topic_id = topic.get("id")
                slug = topic.get("slug")
                if topic_id and slug:
                    url = f"{BASE_URL}/t/{slug}/{topic_id}"
                    threads.append(url)

            # 获取下一页链接
            more_topics_url = data.get("topic_list", {}).get("more_topics_url")
            if more_topics_url:
                # more_topics_url 格式: "/latest.json?no_definitions=true&ascending=false&since=xxx"
                # 需要拼接 BASE_URL
                next_url = BASE_URL + more_topics_url
            else:
                next_url = None

        except Exception as e:
            print(f"⚠️ 抓取API失败: {e}")
            break

    return threads

def extract_yaml_links_from_thread(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text
        urls = re.findall(r'href="([^"]+\.ya?ml)"', text, re.I)
        links = set()
        for href in urls:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = BASE_URL + href
            links.add(href)
        print(f"   📝 {url} 找到 YAML 链接数量: {len(links)}")
        return list(links)
    except Exception as e:
        print(f"⚠️ 解析帖子页面失败：{url}，错误：{e}")
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

    print("🌐 开始通过 Discourse API 爬取 nodefree.net 主题列表...")

    threads = get_threads_with_pagination()
    print(f"\n总共抓取到 {len(threads)} 篇主题")

    all_yaml_links = set()
    for thread_url in threads:
        yaml_links = extract_yaml_links_from_thread(thread_url)
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
