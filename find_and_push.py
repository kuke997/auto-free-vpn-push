import os
import requests
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # 建议设置以避免API限流

# 预定义免费订阅链接
PREDEFINED_URLS = [
    "https://wanmeiwl3.xyz/gywl/4e3979fc330fc6b7806f3dc78a696f10",
    "https://bestsub.bestrui.ggff.net/share/bestsub/cdcefaa4-1f0d-462e-ba76-627b344989f2/all.yaml",
    "https://linuxdo.miaoqiqi.me/linuxdo/love",
    "https://bh.jiedianxielou.workers.dev",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/clash.yaml",
    "https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/clash.yml",
    "https://cdn.jsdelivr.net/gh/vxiaov/free_proxies@main/clash/clash.provider.yaml",
    "https://freenode.openrunner.net/uploads/20240617-clash.yaml",
    "https://tt.vg/freeclash",
    "https://raw.githubusercontent.com/SnapdragonLee/SystemProxy/master/dist/clash_config.yaml"
]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "AutoFreeVPNBot"
}

if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

def github_search_subscribe_files(query="clash.yaml", max_pages=2):
    """
    通过GitHub搜索API，自动发现含clash订阅的yaml文件Raw链接。
    搜索关键词可调整，比如 'clash.yaml', 'subscribe.yaml', 'proxy.yaml'
    """
    print("🔍 GitHub 搜索订阅文件中...")
    discovered_urls = set()

    for page in range(1, max_pages + 1):
        params = {
            "q": query + " in:path",
            "per_page": 30,
            "page": page,
        }
        try:
            resp = requests.get("https://api.github.com/search/code", headers=HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            results = resp.json().get("items", [])
            if not results:
                break
            for item in results:
                # 解析raw文件地址
                repo = item["repository"]["full_name"]
                path = item["path"]
                # GitHub raw文件链接格式
                raw_url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
                discovered_urls.add(raw_url)
        except Exception as e:
            print(f"GitHub 搜索异常: {e}")
            break

    print(f"✨ GitHub 搜索到 {len(discovered_urls)} 个可能的订阅链接")
    return list(discovered_urls)

def validate_subscription(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200 and "proxies" in res.text:
            return True
    except:
        pass
    return False

def send_to_telegram(bot_token, channel_id, urls):
    if not urls:
        print("没有可用节点，跳过推送")
        return
    text = "*🆕 免费节点订阅更新（含GitHub搜索）*:\n\n" + "\n".join(urls[:20])
    bot = Bot(token=bot_token)
    try:
        bot.send_message(chat_id=channel_id, text=text, parse_mode="Markdown")
        print("✅ 推送成功")
    except Exception as e:
        print("❌ 推送失败:", e)

def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("环境变量 BOT_TOKEN 或 CHANNEL_ID 未设置")
        return

    # 1. 验证预定义的链接
    print("🔍 验证预定义订阅链接...")
    valid_urls = [url for url in PREDEFINED_URLS if validate_subscription(url)]

    # 2. GitHub自动搜索并验证
    github_urls = github_search_subscribe_files()
    print("🔍 验证GitHub搜索到的订阅链接...")
    valid_github_urls = [url for url in github_urls if validate_subscription(url)]

    # 合并去重
    all_valid_urls = list(set(valid_urls + valid_github_urls))

    print(f"✔️ 共验证通过的有效订阅链接数量: {len(all_valid_urls)}")
    with open("valid_links.txt", "w") as f:
        for link in all_valid_urls:
            f.write(link + "\n")
    print("📄 已保存到 valid_links.txt")

    # 推送到Telegram频道
    send_to_telegram(BOT_TOKEN, CHANNEL_ID, all_valid_urls)

if __name__ == "__main__":
    main()
