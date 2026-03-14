#!/usr/bin/env python3
"""
Nexora
面向私有媒体库的资源搜索、订阅下载与整理系统
"""

import logging
import signal
import sys
import threading
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from modules.config import Config
from modules.mteam import MTeamClient
from modules.organize import OrganizeConfig, Organizer
from modules.qbit import QBitClient, QBitError
from modules.store import Store
from modules.subscription import SubscriptionManager
from modules.telegram_bot import TelegramBot
from modules.tmdb_client import TmdbClient, TmdbConfig

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    """主程序入口"""
    print("=" * 50)
    print("🚀 Nexora 启动中...")
    print("=" * 50)

    # 加载配置
    try:
        config = Config.load()
        print("✅ 配置加载成功")
    except FileNotFoundError as e:
        print(f"❌ 配置文件错误: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ 配置验证失败:\n{e}")
        sys.exit(1)

    # 初始化 M-Team 客户端
    try:
        mteam = MTeamClient(
            api_key=config.mteam["api_key"],
            domain=config.mteam.get("domain", "m-team.io"),
            categories_config=config.mteam_categories,
        )

        # 测试连接
        success, message = mteam.test_connection()
        if success:
            print("✅ M-Team API 连接成功")
        else:
            print(f"⚠️ M-Team API 连接失败: {message}")
            sys.exit(1)

    except Exception as e:
        print(f"❌ M-Team 初始化失败: {e}")
        sys.exit(1)

    # 初始化 qBittorrent 客户端
    try:
        qbit = QBitClient(
            host=config.qbittorrent["host"],
            port=config.qbittorrent.get("port", 8080),
            username=config.qbittorrent.get("username", "admin"),
            password=config.qbittorrent.get("password", ""),
        )

        # 测试连接
        if qbit.test_connection():
            version = qbit.get_version()
            print(f"✅ qBittorrent 连接成功 (版本: {version})")
        else:
            print("⚠️ qBittorrent 连接失败，请检查配置")
            sys.exit(1)

    except QBitError as e:
        print(f"❌ qBittorrent 初始化失败: {e}")
        sys.exit(1)

    # 全局 Store（整理/订阅共享）
    store = Store(db_path=str(Path("data/organize.db").resolve()))

    # 初始化 Telegram Bot
    try:
        bot = TelegramBot(config=config, mteam=mteam, qbit=qbit, store=store)
        print("✅ Telegram Bot 初始化成功")
    except Exception as e:
        print(f"❌ Telegram Bot 初始化失败: {e}")
        sys.exit(1)

    # 启动自动整理调度（mode=auto/both）
    org_cfg = config.organize or {}
    sub_cfg = config.subscription or {}
    scheduler = None
    tmdb_client = None
    try:
        tmdb_cfg = org_cfg.get("tmdb") or {}
        if tmdb_cfg.get("api_key"):
            tmdb_client = TmdbClient(
                TmdbConfig(
                    api_key=tmdb_cfg.get("api_key"),
                    language=tmdb_cfg.get("language", "zh-CN"),
                    image_domain=tmdb_cfg.get("image_domain", "image.tmdb.org"),
                    scrap_original_image=bool(tmdb_cfg.get("scrap_original_image", False)),
                )
            )
    except Exception as e:
        print(f"⚠️ TMDB 初始化失败：{e}")

    try:
        scheduler = BackgroundScheduler()

        if org_cfg.get("enabled") and str(org_cfg.get("mode", "both")) in (
            "auto",
            "both",
        ):
            oc = OrganizeConfig(
                enabled=bool(org_cfg.get("enabled")),
                mode=str(org_cfg.get("mode", "both")),
                interval_minutes=int(org_cfg.get("interval_minutes", 10)),
                dry_run=bool(org_cfg.get("dry_run", False)),
                download_root=str(org_cfg.get("download_root", "/downloads")),
                path_mappings=list(org_cfg.get("path_mappings") or []),
                libraries=dict(org_cfg.get("libraries") or {}),
                naming=dict(org_cfg.get("naming") or {}),
                filters=dict(org_cfg.get("filters") or {}),
                tmdb=dict(org_cfg.get("tmdb") or {}),
                strict_id=dict(org_cfg.get("strict_id") or {}),
            )
            organizer = Organizer(cfg=oc, store=store, qbit=qbit)

            def _auto_job():
                try:
                    torrents = qbit.get_torrents_by_status(status_filter="completed", limit=20)
                    for t in torrents:
                        th = t.get("hash") or ""
                        if not th:
                            continue
                        files = qbit.get_torrent_files(th)
                        base_path = t.get("save_path") or t.get("content_path") or ""
                        if not base_path:
                            continue
                        organizer.copy_to_library(
                            torrent_hash=th,
                            base_path=base_path,
                            files=files,
                            torrent_info={
                                "name": t.get("name") or "",
                                "small_descr": "",
                                "labels_new": [],
                                "imdb_url": "",
                            },
                        )
                except Exception as e:
                    logger.error(f"自动整理任务失败: {e}")

            interval = int(org_cfg.get("interval_minutes", 10))
            scheduler.add_job(
                _auto_job,
                "interval",
                minutes=max(1, interval),
                id="auto_organize",
                replace_existing=True,
            )
            print(f"✅ 自动整理已启用（每 {interval} 分钟扫描一次）")

        # 订阅轮询
        if sub_cfg.get("enabled") and tmdb_client:
            # 订阅管理器
            libraries = org_cfg.get("libraries") or {}
            sub_mgr = SubscriptionManager(
                store=store,
                tmdb=tmdb_client,
                pt_client=mteam,  # MTeamClient 实现 PTClient 接口
                qbit=qbit,
                libraries=libraries,
                notifier=lambda text: (
                    bot.bot.send_message(config.telegram_chat_id or config.telegram.get("chat_id"), text)
                    if (config.telegram_chat_id or config.telegram.get("chat_id"))
                    else None
                ),
            )
            bot.set_subscription_manager(sub_mgr)

            sub_interval = int(sub_cfg.get("interval_minutes", 30))
            max_subs = int(sub_cfg.get("max_subscriptions", 20))
            max_items = int(sub_cfg.get("max_items_per_sub", 5))

            def _sub_job():
                try:
                    sub_mgr.poll_and_download(max_subs=max_subs, max_items_per_sub=max_items)
                except Exception as e:
                    logger.error(f"订阅轮询失败: {e}")

            scheduler.add_job(
                _sub_job,
                "interval",
                minutes=max(1, sub_interval),
                id="subscription_poll",
                replace_existing=True,
            )
            print(f"✅ 订阅轮询已启用（每 {sub_interval} 分钟扫描一次）")

        if scheduler.get_jobs():
            scheduler.start()
    except Exception as e:
        print(f"⚠️ 调度初始化失败：{e}")

    # 设置信号处理
    def signal_handler(sig, frame):
        print("\n⏹️ 收到停止信号，正在退出...")
        try:
            if scheduler:
                scheduler.shutdown(wait=False)
        except Exception:
            pass
        bot.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 获取订阅管理器引用（如果已创建）
    # sub_mgr 在上面的订阅轮询初始化中已创建
    sub_mgr_ref = None
    if sub_cfg.get("enabled") and tmdb_client:
        # 重新获取引用（因为 sub_mgr 在 try 块内创建，作用域限制）
        libraries = org_cfg.get("libraries") or {}
        sub_mgr_ref = SubscriptionManager(
            store=store,
            tmdb=tmdb_client,
            pt_client=mteam,
            qbit=qbit,
            libraries=libraries,
            notifier=lambda text: (
                bot.bot.send_message(config.telegram_chat_id or config.telegram.get("chat_id"), text)
                if (config.telegram_chat_id or config.telegram.get("chat_id"))
                else None
            ),
        )

    # 启动 FastAPI 服务 (后台线程)
    api_port = config.api.get("port", 8000)
    api_enabled = config.api.get("enabled", True)

    def start_api_server():
        """在后台线程中启动 FastAPI 服务"""
        try:
            import uvicorn

            from api.app import create_app, init_app_state
            from modules.organize_local import LocalOrganizer

            # 获取 organizer 和 org_queue
            organizer = getattr(bot, "organizer", None)
            org_queue = getattr(bot, "org_queue", None)

            # 创建本地整理器（用于文件管理功能）
            local_organizer = None
            if organizer and store:
                # 构建允许的根目录列表
                fm_cfg = config.file_manager or {}
                org_cfg = config.organize or {}
                allowed_roots = []

                # 默认包含 download_root
                if org_cfg.get("download_root"):
                    allowed_roots.append(org_cfg["download_root"])

                # 默认包含 libraries.*
                for lib_path in (org_cfg.get("libraries") or {}).values():
                    if lib_path:
                        allowed_roots.append(lib_path)

                # 额外配置的 allowed_roots
                for r in fm_cfg.get("allowed_roots") or []:
                    if r:
                        allowed_roots.append(r)

                local_organizer = LocalOrganizer(
                    organizer=organizer,
                    store=store,
                    allowed_roots=allowed_roots,
                )

            # 初始化 API 状态（共享客户端实例）
            # 使用 TelegramBot 内部的 organizer 和 org_queue（保持与 TG 整理逻辑一致）
            init_app_state(
                mteam=mteam,
                qbit=qbit,
                store=store,
                tmdb=tmdb_client,
                subscription_manager=sub_mgr_ref,
                organizer=organizer,
                organize_queue=org_queue,
                local_organizer=local_organizer,
                config=config,
            )

            app = create_app()
            print(f"🌐 API 服务启动于 http://0.0.0.0:{api_port}")
            uvicorn.run(app, host="0.0.0.0", port=api_port, log_level="warning")
        except Exception as e:
            logger.error(f"API 服务启动失败: {e}")

    if api_enabled:
        api_thread = threading.Thread(target=start_api_server, daemon=True)
        api_thread.start()

    # 启动 Bot
    print("=" * 50)
    print("📱 使用方法:")
    print("   发送 /search 关键词 或 搜索 关键词")
    print("   发送 /status 查看下载状态")
    print("   发送 /help 查看帮助")
    if api_enabled:
        print(f"🌐 Web API: http://localhost:{api_port}/docs")
    print("=" * 50)

    try:
        bot.start_polling()
    except Exception as e:
        logger.error(f"Bot 运行错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
