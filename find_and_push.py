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

def get_threads_via_sitemap():
    """
    从 https://nodefree.net/sitemap.xml 提取所有 <loc>，
    筛选出形如 https://nodefree.net/p/数字.html 的文章链接
    """
    sitemap_url = BASE_URL + "/sitemap.xml"
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        xml_text = resp.text
        # 匹配所有 <loc>…</loc> 中间的 URL
        locs = re.findall(r"<loc>(.*?)</loc>", xml_text)
        # 只保留 /p/数字.html 格式
        threads = [u for u in locs if re.match(rf"{re.escape(BASE_URL)}/p/\d+\.html$", u)]
        print(f"✅ 从 sitemap.xml 找到 {len(threads)} 篇文章")
        return threads
    except Exception as e:
        print(f"⚠️ 获取 sitemap 失败: {e}")
        return []

def extract_yaml_links_from_thread(url):
    """
    从单个文章页面抓取所有以 .yaml 或 .yml 结尾的链接
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"\.ya?ml$", href, re.I):
                # 补齐相对链接
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = urljoin(BASE_URL, href)
                links.add(href)
        print(f"   📝 {url} 找到 {len(links)} 个 YAML 链接")
        return list(links)
    except Exception as e:
        print(f"⚠️ 解析文章页面失败：{url}，错误：{e}")
        return []

def validate_subscription(url):
    """
    验证订阅链接是否有效（通过内容中包含 proxies/vmess/ss/clash 判断）
    """
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"    ❌ 验证失败 (HTTP {res.status_code}): {url}")
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
    通过 Telegram Bot 发送有效的订阅链接
    """
    if not urls:
        print("❌ 无有效链接，跳过推送")
        return

    text = "🆕 <b>最新 NodeFree 免费VPN订阅合集</b>\n\n"
    for url in urls[:20]:
        safe_url = quote(url, safe=":/?=&")
        text += f"👉 <a href=\"{safe_url}\">{url}</a>\n\n"

    # 避免超过 4096 字节限制
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
    print("🌐 开始通过 Sitemap 爬取 nodefree.net 文章列表...")
    threads = get_threads_via_sitemap()  # 获取所有文章链接
    print(f"总共抓取到 {len(threads)} 篇文章\n")

    all_yaml_links = set()
    for thread_url in threads:
        yaml_links = extract_yaml_links_from_thread(thread_url)
        all_yaml_links.update(yaml_links)

    print(f"\n🔍 开始验证 {len(all_yaml_links)} 条订阅链接")
    valid_links = [u for u in all_yaml_links if validate_subscription(u)]
    print(f"\n✔️ 有效订阅链接数量: {len(valid_links)}")

    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)

if __name__ == "__main__":
    asyncio.run(main())
