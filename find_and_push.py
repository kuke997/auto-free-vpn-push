import requests
from bs4 import BeautifulSoup
import re
import logging
import time
from urllib.parse import urljoin

# =========================
# 配置区域
# =========================
BASE_URL = "https://nodefree.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}
TG_BOT_TOKEN = "<你的BotToken>"
TG_CHAT_ID = "<你的频道或用户ID>"

# =========================
# 日志设置
# =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# =========================
# 节点提取函数
# =========================
def extract_freenodes_links():
    url = "https://freenodes.github.io/freenodes/"
    logger.info(f"🌐 正在爬取 Freenodes 页面: {url}")
    links = set()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a in soup.select('a[href]'):
            href = a['href']
            if any(ext in href for ext in ['.yaml', 'subscribe', 'clash']):
                if not href.startswith('http'):
                    href = urljoin(url, href)
                links.add(href)
        logger.info(f"   🔗 Freenodes 提取到 {len(links)} 个订阅链接")
    except Exception as e:
        logger.error(f"❌ Freenodes 提取失败: {str(e)}")
    return list(links)

def extract_freefq_links():
    url = "https://freefq.com/free-ssr/"
    logger.info(f"🌐 正在爬取 FreeFQ 页面: {url}")
    links = set()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a in soup.select('a[href]'):
            href = a['href']
            if any(x in href for x in ['subscribe', 'clash', 'yaml']):
                if not href.startswith('http'):
                    href = urljoin(url, href)
                links.add(href)
        logger.info(f"   🔗 FreeFQ 提取到 {len(links)} 个链接")
    except Exception as e:
        logger.error(f"❌ FreeFQ 提取失败: {str(e)}")
    return list(links)

def extract_proxypoolss_links():
    url = "https://proxypoolss.pages.dev"
    logger.info(f"🌐 正在爬取 ProxyPoolss 页面: {url}")
    links = set()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        links.update(re.findall(r'https?://[\w./%-]+\.yaml', resp.text))
        logger.info(f"   🔗 ProxyPoolss 提取到 {len(links)} 个链接")
    except Exception as e:
        logger.error(f"❌ ProxyPoolss 提取失败: {str(e)}")
    return list(links)

def extract_clashfree_links():
    base_url = "https://raw.githubusercontent.com/aiboboxx/clashfree/main/"
    files = ["clash.yaml", "clash.meta.yaml"]
    links = [base_url + f for f in files]
    logger.info(f"🌐 从 GitHub aiboboxx 添加静态订阅链接: {len(links)}")
    return links

def get_threads_on_page(page_num):
    page_url = f"{BASE_URL}/page/{page_num}" if page_num > 1 else BASE_URL
    logger.info(f"🔍 正在爬取页面: {page_url}")
    threads = []
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for article in soup.select('article'):
            a_tag = article.select_one('h2.entry-title a')
            if a_tag:
                href = a_tag.get('href')
                threads.append(href)
        logger.info(f"✅ 找到 {len(threads)} 篇文章")
    except Exception as e:
        logger.warning(f"⚠️ 第 {page_num} 页未找到文章，跳过: {str(e)}")
    return threads

def extract_nodefree_links():
    logger.info(f"🌐 正在爬取 NodeFree 网页")
    links = set()
    for i in range(1, 3):
        threads = get_threads_on_page(i)
        for url in threads:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')
                text = soup.get_text()
                found = re.findall(r'https?://[\w./%-]+\.(?:yaml|txt)', text)
                links.update(found)
            except Exception as e:
                logger.warning(f"⚠️ 文章抓取失败: {url}, 错误: {str(e)}")
    return list(links)

def is_valid_subscription(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"    ❌ HTTP {resp.status_code}: {url}")
            return False
        if not re.search(r'(proxy-groups|proxies|server|name)', resp.text, re.IGNORECASE):
            logger.warning(f"    ❌ 无效订阅 (无VPN配置): {url}")
            return False
        logger.info(f"    ✔️ 有效订阅: {url}")
        return True
    except Exception as e:
        logger.warning(f"    ❌ 验证失败: {url} -> {str(e)}")
        return False

def push_to_telegram(message):
    api_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(api_url, data=payload)
        logger.info(f"✅ 推送成功")
    except Exception as e:
        logger.error(f"❌ 推送失败: {str(e)}")

# =========================
# 主流程
# =========================
def main():
    logger.info("=" * 50)
    logger.info(f"🌐 NodeFree + Freenodes 爬虫启动 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    all_links = set()

    all_links.update(extract_nodefree_links())
    all_links.update(extract_freenodes_links())
    all_links.update(extract_freefq_links())
    all_links.update(extract_proxypoolss_links())
    all_links.update(extract_clashfree_links())

    logger.info(f"\n🔍 共提取到 {len(all_links)} 条订阅链接，开始验证...")

    valid_links = []
    for link in all_links:
        logger.info(f"🔐 正在验证链接: {link}")
        if is_valid_subscription(link):
            valid_links.append(link)

    logger.info(f"\n✔️ 验证完成！共 {len(valid_links)} 条有效订阅链接")

    with open("valid_links.txt", "w") as f:
        for link in valid_links:
            f.write(link + "\n")
    logger.info("📄 结果已保存到 valid_links.txt")

    if valid_links:
        msg = "\n".join(valid_links)
        push_to_telegram("<b>📡 今日有效订阅链接:</b>\n" + msg)

    logger.info("\n✅ 任务完成！")

if __name__ == '__main__':
    main()
