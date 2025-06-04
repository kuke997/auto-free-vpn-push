import os
import requests
import asyncio
import yaml
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
import urllib.parse

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

def validate_subscription(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200 and "proxies" in res.text:
            return True
    except:
        pass
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
            country = proxy.get("country")
            if country and isinstance(country, str) and len(country) <= 5:
                countries.add(country.strip())
                continue

            region = proxy.get("region")
            if region and isinstance(region, str) and len(region) <= 5:
                countries.add(region.strip())
                continue

            name = proxy.get("name") or proxy.get("remark") or proxy.get("remarks")
            if name and isinstance(name, str) and len(name) >= 2:
                countries.add(name[:2].strip())

        return ", ".join(sorted(countries)) if countries else None
    except Exception as e:
        print(f"解析节点地区失败：{url}，错误：{e}")
        return None

def fetch_nodefree_links():
    print("🌐 正在抓取 nodefree.net 最新节点...")
    try:
        base_url = "https://nodefree.net"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(base_url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')

        post_link = None
        for a in soup.find_all('a'):
            if '免费节点' in a.text:
                post_link = a['href']
                break

        if not post_link:
            print("❌ 没有找到最新节点文章")
            return []

        full_url = post_link if post_link.startswith("http") else base_url + post_link
        res = requests.get(full_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')

        found_links = []
        for a in soup.find_all('a'):
            href = a.get('href', '')
            if href.startswith("http") and (".yaml" in href or "vmess://" in href or "ss://" in href):
                found_links.append(href.strip())

        print(f"📥 nodefree.net 提取到 {len(found_links)} 个订阅链接")
        return found_links
    except Exception as e:
        print("❌ 抓取 nodefree.net 失败:", e)
        return []

async def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        print("❌ 没有可用节点，跳过推送")
        return

    text = "🆕 <b>2025年最新Clash订阅节点 免费vpn节点Clash/V2Ray/Shadowsocks/Vmess订阅更新 适合翻墙科学上网、免费高速V2Ray节点推荐节点订阅</b>\n\n"
    for i, url in enumerate(urls[:20], start=1):
        country_info = get_subscription_country_info(url)
        if country_info:
            country_info = f"（节点地区: {country_info}）"
        else:
            country_info = ""

        safe_url = urllib.parse.quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a> {country_info}\n（可长按复制，或粘贴到 Clash / Shadowrocket 导入）\n\n"

    if len(text.encode('utf-8')) > 4000:
        text = text.encode("utf-8")[:4000].decode("utf-8", errors="ignore") + "\n..."

    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        print("✅ 推送成功")
    except Exception as e:
        print("❌ 推送失败:", e)

async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("环境变量 BOT_TOKEN 或 CHANNEL_ID 未设置")
        return

    nodefree_links = fetch_nodefree_links()
    print("🔍 验证 nodefree.net 获取到的链接...")
    valid_links = [url for url in nodefree_links if validate_subscription(url)]

    print(f"✔️ 有效订阅链接数量: {len(valid_links)}")
    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
