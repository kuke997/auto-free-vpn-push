import os
import re
import requests
import asyncio
import yaml
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
import urllib.parse

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")


def fetch_nodefree_links():
    print("🌐 正在抓取 nodefree.net 首页所有可能的订阅链接...")
    try:
        base_url = "https://nodefree.net"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(base_url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        found_links = set()

        # 查找所有<a>标签，href中包含 .yaml 或 .yml 或 clash (不区分大小写)
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"\.ya?ml", href, re.I) or re.search(r"clash", href, re.I):
                # 补全相对链接
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = base_url + href
                found_links.add(href)

        links = list(found_links)
        print(f"📥 nodefree.net 首页提取到 {len(links)} 个可能的订阅链接")
        return links
    except Exception as e:
        print("❌ 抓取失败:", e)
        return []


def validate_subscription(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return False
        text = res.text.lower()
        # 简单判定是否含有节点关键词
        if "proxies" in text or "vmess://" in text or "ss://" in text or "clash" in text:
            return True
        return False
    except Exception:
        return False


def get_subscription_country_info(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return None
        data = yaml.safe_load(res.text)
        proxies = data.get("proxies", [])
        countries = set()
        for proxy in proxies:
            country = proxy.get("country") or proxy.get("region")
            if country and isinstance(country, str) and len(country) <= 5:
                countries.add(country.strip())
                continue
            name = proxy.get("name") or proxy.get("remark") or proxy.get("remarks")
            if name and isinstance(name, str) and len(name) >= 2:
                countries.add(name[:2].strip())
        return ", ".join(sorted(countries)) if countries else None
    except Exception as e:
        print(f"⚠️ 地区解析失败: {url}, 错误: {e}")
        return None


async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        print("❌ 没有可用节点，跳过推送")
        return

    text = "🆕 <b>2025年最新免费VPN节点合集（Clash/V2Ray/SS）</b>\n\n"
    for i, url in enumerate(urls[:20], start=1):
        country_info = get_subscription_country_info(url)
        if country_info:
            country_info = f"（地区: {country_info}）"
        else:
            country_info = ""
        safe_url = urllib.parse.quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a> {country_info}\n\n"

    if len(text.encode("utf-8")) > 4000:
        text = text.encode("utf-8")[:4000].decode("utf-8", errors="ignore") + "\n..."

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        print("✅ 推送成功")
    except Exception as e:
        print("❌ 推送失败:", e)


async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("❌ 未设置 BOT_TOKEN 或 CHANNEL_ID")
        return

    links = fetch_nodefree_links()
    print("🔍 验证 nodefree.net 获取到的链接...")
    valid_links = [url for url in links if validate_subscription(url)]
    print(f"✔️ 有效订阅链接数量: {len(valid_links)}")

    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)


if __name__ == "__main__":
    asyncio.run(main())
