import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
import urllib.parse

# Telegram Bot 配置，建议用环境变量传入
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
    抓取列表页所有文章链接，返回完整URL列表（去重）
    只抓取 href 形如 /t/xxx 或 /t/xxx/数字 的链接
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        threads = set()
        for a in soup.select("a[href^='/t/']"):
            href = a.get("href")
            if href and re.match(r"^/t/[^/]+(/[\d]+)?$", href):
                full_url = BASE_URL + href
                threads.add(full_url)
        return list(threads)
    except Exception as e:
        print(f"⚠️ 获取列表页文章失败：{url}，错误：{e}")
        return []

def extract_yaml_links_from_thread(url):
    """
    解析单个文章页面，提取所有以 .yaml/.yml 结尾的链接
    自动补全相对URL为绝对URL
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"\.ya?ml$", href, re.I):
                # 补全链接
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
    """
    简单校验订阅链接是否有效
    通过访问内容包含常见VPN关键词判断
    """
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return False
        text = res.text.lower()
        if any(k in text for k in ("proxies", "vmess://", "ss://", "clash")):
            return True
        return False
    except Exception:
        return False

async def send_to_telegram(bot_token, channel_id, urls):
    """
    通过 Telegram Bot 发送订阅链接合集消息
    """
    if not urls:
        print("❌ 没有可用节点，跳过推送")
        return

    text = "🆕 <b>2025年 nodefree.net 免费VPN订阅合集（Clash/V2Ray/SS）</b>\n\n"
    for i, url in enumerate(urls[:20], start=1):
        safe_url = urllib.parse.quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a>\n\n"

    # 限制消息长度，避免被截断
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
        print("✅ 推送成功")
    except Exception as e:
        print("❌ 推送失败:", e)

async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("❌ 未设置 BOT_TOKEN 或 CHANNEL_ID")
        return

    print("🌐 开始爬取 nodefree.net 最新文章列表...")
    all_yaml_links = set()

    # 抓取 /latest 及其分页 /latest/page/2, /latest/page/3
    for page_num in range(1, 4):
        if page_num == 1:
            url = f"{BASE_URL}/latest"
        else:
            url = f"{BASE_URL}/latest/page/{page_num}"
        print(f"➡️ 抓取列表页: {url}")
        threads = get_threads_on_page(url)
        print(f" 发现 {len(threads)} 篇文章")

        for thread_url in threads:
            print(f"   ↪️ 解析文章: {thread_url}")
            yaml_links = extract_yaml_links_from_thread(thread_url)
            print(f"      找到 {len(yaml_links)} 个 YAML 链接")
            all_yaml_links.update(yaml_links)

    print(f"🔍 验证订阅链接有效性，共 {len(all_yaml_links)} 个")
    valid_links = [url for url in all_yaml_links if validate_subscription(url)]
    print(f"✔️ 有效订阅链接数量: {len(valid_links)}")

    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
