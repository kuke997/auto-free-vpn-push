import asyncio
import logging

from vpn_check import check_subscribe_links
from push import push_to_telegram
from sources.static_sources import get_static_sources
from sources.github_sources import get_github_sources
from freefq_spider import get_freefq_subscribe_urls

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def main():
    logger.info("📦 启动订阅链接收集与推送流程")

    # ===== 1. 收集所有候选链接 =====
    static_links = get_static_sources()
    github_links = await get_github_sources()
    freefq_links = await get_freefq_subscribe_urls()

    all_links = list(set(static_links + github_links + freefq_links))
    logger.info(f"📊 共收集 {len(all_links)} 条“候选”链接，准备进行有效性验证")

    # ===== 2. 验证链接可用性 =====
    valid_links = await check_subscribe_links(all_links)

    if not valid_links:
        logger.warning("❌ 无有效链接，跳过推送")
        return

    logger.info(f"✅ 共 {len(valid_links)} 条链接通过验证，准备推送")

    # ===== 3. 推送到 Telegram =====
    await push_to_telegram(valid_links)

    logger.info("✅ 完成！所有节点已推送到频道")


if __name__ == "__main__":
    asyncio.run(main())
