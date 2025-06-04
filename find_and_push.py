import os
import re
import asyncio
import requests
from telegram import Bot
from telegram.constants import ParseMode
from urllib.parse import urljoin, quote

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
BASE_URL = "https://nodefree.net"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_threads_on_page(page):
    """
    从 nodefree.net 列表页中，用正则提取所有 /p/数字.html 文章链接
    """
    url = BASE_URL if page == 1 else f"{BASE_URL}/page/{page}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
        # 先找绝对链接
        abs_links = re.findall(r"https://nodefree\\.net/p/\\d+\\.html", html)
        # 再找相对链接并拼接
        rel_links = re.findall(r'href="(/p/\\d+\\.html)"', html)
        rel_links = [urljoin(BASE_URL, l) for l in rel_links]
        threads = list(set(abs_links + rel_links))
        print(f"➡️ {url} 找到 {len(threads)} 篇文章")
        return threads
    except Exception as e:
        print(f"⚠️ 获取页面失败 {url} 错误: {e}")
        return []


def extract_yaml_links_from_thread(url):
    """
    从单个文章页面中，用正则提取所有 .yaml/.yml 订阅链接，以及 nodefree.githubrowcontent.com/*.txt 链接
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
        # 匹配所有以 .yaml 或 .yml 结尾的 URL
        links = re.findall(r"https?://[^\"'\\s]+?\\.ya?ml", html, re.I)
        # 匹配 nodefree.githubrowcontent.com/*.txt
        more = re.findall(r"https?://nodefree\\.githubrowcontent\\.com/[^\"'\\s]+?\\.txt", html, re.I)
        links += more
        links = list(set(links))
        print(f"   📝 {url} 提取到 {len(links)} 个订阅链接")
        return links
    except Exception as e:
        print(f"⚠️ 解析帖子失败 {url} 错误: {e}")
        return []


def validate_subscription(url):
    """
    简单访问订阅链接，判断内容里是否包含常见节点关键词
    """
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"    ❌ HTTP {res.status_code}: {url}")
            return False
        text = res.text.lower()
        if any(k in text for k in ("proxies", "vmess://", "ss://", "clash")):
            print(f"    ✔️ 有效订阅: {url}")
            return True
        print(f"    ❌ 无效订阅: {url}")
        return False
    except Exception as e:
        print(f"    ❌ 验证异常: {url}，错误: {e}")
        return False


async def send_to_telegram(bot_token, channel_id, urls):
    """
    将有效订阅链接推送到 Telegram 频道
    """
    if not urls:
        print("❌ 无有效链接，跳过推送")
        return

    text = "🆕 <b>NodeFree 最新免费VPN订阅合集</b>\n\n"
    for u in urls[:20]:
        safe = quote(u, safe=":/?=&")
        text += f"👉 <a href=\"{safe}\">{u}</a>\n\n"

    # 控制消息长度
    text = text[:3900]

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
    print("🌐 开始爬取 NodeFree 文章列表…")
    all_yaml_links = set()

    # 爬取前 4 页列表（可根据需要增加页数）
    for page in range(1, 5):
        threads = get_threads_on_page(page)
        for t in threads:
            subs = extract_yaml_links_from_thread(t)
            all_yaml_links.update(subs)

    print(f"\n🔍 共提取到 {len(all_yaml_links)} 条订阅链接，开始验证…")
    valid_links = []
    for link in all_yaml_links:
        if validate_subscription(link):
            valid_links.append(link)

    print(f"\n✔️ 共 {len(valid_links)} 条有效订阅链接")
    with open("valid_links.txt", "w") as f:
        for v in valid_links:
            f.write(v + "\n")
    print("📄 已保存到 valid_links.txt")

    if BOT_TOKEN and CHANNEL_ID:
        await send_to_telegram(BOT_TOKEN, CHANNEL_ID, valid_links)


if __name__ == "__main__":
    asyncio.run(main())
