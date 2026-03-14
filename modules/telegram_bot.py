"""
Telegram Bot 交互模块
实现用户交互、搜索、下载流程
"""

import contextlib
import logging
from pathlib import Path

import telebot
from telebot.types import (
    BotCommand,
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from .config import Config
from .mteam import MTeamAPIError, MTeamClient, TorrentInfo
from .organize import OrganizeConfig, Organizer
from .organize_queue import OrganizeQueue
from .qbit import QBitClient, QBitError
from .store import Store

logger = logging.getLogger(__name__)


class UserSession:
    """用户会话数据"""

    def __init__(self):
        self.keyword: str | None = None
        self.category: str | None = None
        self.results: list[TorrentInfo] = []
        self.page: int = 1
        self.message_id: int | None = None
        self.pending_torrent_id: str | None = None  # 待下载的种子 ID
        self.awaiting_keyword: bool = False  # 是否等待用户输入关键词（用于菜单按钮）
        self.awaiting_subscribe: bool = False  # 是否等待订阅关键词
        self.sub_type: str | None = None  # 预选订阅类型 tv/movie（可为空）
        self.sub_query: str | None = None
        self.sub_season_hint: int | None = None


class TelegramBot:
    """Telegram Bot 控制器"""

    def __init__(
        self,
        config: Config,
        mteam: MTeamClient,
        qbit: QBitClient,
        store: Store | None = None,
    ):
        """
        初始化 Telegram Bot

        :param config: 配置对象
        :param mteam: M-Team 客户端
        :param qbit: qBittorrent 客户端
        """
        self.config = config
        self.mteam = mteam
        self.qbit = qbit

        self.bot = telebot.TeleBot(config.telegram["token"], parse_mode="HTML")
        self.sessions: dict[int, UserSession] = {}
        self._setup_menu()
        self._setup_handlers()

        # Organizer（手动模式使用；自动调度在 main.py 里启动）
        org_cfg = config.organize or {}
        self.organizer: Organizer | None = None
        self.org_store: Store | None = store or Store(db_path=str(Path("data/organize.db").resolve()))
        self.org_queue: OrganizeQueue | None = None
        try:
            if org_cfg.get("enabled"):
                self.org_queue = OrganizeQueue(store=self.org_store)
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
                self.organizer = Organizer(cfg=oc, store=self.org_store, qbit=qbit)
        except Exception as e:
            logger.warning(f"Organizer 初始化失败: {e}")

        # 订阅管理器（由 main 注入）
        self.sub_mgr = None

    def set_subscription_manager(self, sub_mgr):
        self.sub_mgr = sub_mgr

    def _setup_menu(self):
        """
        设置 Telegram 命令菜单（无需每次手动输入 /search）
        """
        try:
            self.bot.set_my_commands(
                [
                    BotCommand("search", "搜索资源（也可直接点键盘里的🔍 搜索）"),
                    BotCommand("status", "查看下载状态"),
                    BotCommand("organize", "手动整理：扫描已完成任务并复制到 NAS"),
                    BotCommand("org_status", "整理进度：查看历史任务/进行中/失败原因"),
                    BotCommand("subscribe", "添加订阅：/subscribe <tmdb_id> <tv|movie>"),
                    BotCommand("subs", "查看/管理订阅"),
                    BotCommand("help", "帮助"),
                ]
            )
        except Exception as e:
            logger.warning(f"设置 Telegram 菜单失败: {e}")

    @staticmethod
    def _main_keyboard() -> ReplyKeyboardMarkup:
        """
        生成底部快捷键盘（用户点按钮即可触发）
        """
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("🔍 搜索"), KeyboardButton("📊 状态"))
        kb.row(KeyboardButton("🧹 整理"), KeyboardButton("📋 进度"))
        kb.row(KeyboardButton("❓ 帮助"))
        return kb

    def _prompt_keyword(self, message: Message):
        """
        提示用户输入搜索关键词：
        - 用于底部“🔍 搜索”按钮
        - 也用于用户从菜单点击 /search（Telegram 会直接发送 /search）
        """
        session = self._get_session(message.from_user.id)
        session.awaiting_keyword = True
        # ForceReply 可以让客户端更明确地进入“请输入内容”的状态
        self.bot.reply_to(
            message,
            "请输入要搜索的关键词（支持 IMDB ID，如 tt1234567）：",
            reply_markup=ForceReply(selective=True),
        )

    def _prompt_subscribe(self, message: Message):
        """
        提示用户输入订阅关键词（TMDB 搜索用），类似搜索流程
        """
        session = self._get_session(message.from_user.id)
        session.awaiting_subscribe = True
        session.sub_type = None
        self.bot.reply_to(
            message,
            "请输入要订阅的片名（会搜索 TMDB 供你选择）\n示例：生活大爆炸 S05 或 疯狂动物城",
            reply_markup=ForceReply(selective=True),
        )

    def _get_session(self, user_id: int) -> UserSession:
        """获取或创建用户会话"""
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession()
        return self.sessions[user_id]

    def _check_permission(self, user_id: int) -> bool:
        """检查用户权限"""
        chat_id = self.config.telegram_chat_id
        admins = self.config.telegram_admins

        # 如果没有配置限制，允许所有用户
        if not chat_id and not admins:
            return True

        user_id_str = str(user_id)

        # 检查是否在白名单
        if chat_id and user_id_str == chat_id:
            return True
        return bool(admins and user_id_str in admins)

    def _setup_handlers(self):
        """设置消息处理器"""

        @self.bot.message_handler(commands=["start", "help"])
        def handle_start(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return

            help_text = (
                "🎬 <b>Nexora</b>\n"
                "你的资源流转助手\n\n"
                "📖 <b>搜索下载：</b>\n"
                "• 点击 <b>🔍 搜索</b> 然后输入关键词\n"
                "• 或发送 <code>/search 关键词</code>\n"
                "• 或发送 <code>搜索 关键词</code>\n"
                "• 支持 IMDB ID，如 <code>/search tt1234567</code>\n\n"
                "📂 <b>下载管理：</b>\n"
                "• <code>/status</code> - 查看下载状态\n\n"
                "🧹 <b>媒体整理：</b>\n"
                "• <code>/organize</code> - 手动整理（已完成任务→NAS）\n"
                "• <code>/org_status</code> - 查看整理进度/历史\n\n"
                "📺 <b>订阅：</b>\n"
                "• <code>/subscribe tmdb_id tv|movie</code> - 添加订阅\n"
                "• <code>/subs</code> - 查看/删除订阅\n"
                "• <code>/sub_status id</code> - 查看订阅详情\n\n"
                "💡 <b>提示：</b>\n"
                "• 整理会自动识别电影/剧集\n"
                "• 从 TMDB 获取中英文标题\n"
                "• 生成 NFO、海报等刮削文件"
            )
            self.bot.reply_to(message, help_text, reply_markup=self._main_keyboard())

        @self.bot.message_handler(func=lambda m: m.text in ("🔍 搜索", "📊 状态", "🧹 整理", "📋 进度", "❓ 帮助"))
        def handle_quick_buttons(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return

            if message.text == "📊 状态":
                self._show_download_status(message)
                return

            if message.text == "🧹 整理":
                if not self.organizer:
                    self.bot.reply_to(message, "❌ 未启用整理功能")
                    return
                self._manual_organize_scan(message)
                return

            if message.text == "📋 进度":
                if not self.org_store:
                    self.bot.reply_to(message, "❌ 未启用整理功能")
                    return
                self._show_org_status(message)
                return

            if message.text == "❓ 帮助":
                handle_start(message)
                return

            # 其他按钮（可扩展）：订阅
            if message.text.strip() in ("订阅",):
                self._prompt_subscribe(message)
                return

            # 🔍 搜索
            self._prompt_keyword(message)

        def _is_awaiting_keyword(m: Message) -> bool:
            """
            仅当用户处于“等待输入关键词”状态时，才处理普通文本；
            避免拦截 /search、"搜索 xxx" 等其他处理器。
            """
            if not m or not getattr(m, "text", None) or not getattr(m, "from_user", None):
                return False
            session = self.sessions.get(m.from_user.id)
            return bool(session and session.awaiting_keyword)

        @self.bot.message_handler(func=_is_awaiting_keyword)
        def handle_keyword_input(message: Message):
            """当用户点击“🔍 搜索”后，下一条文本会被当作关键词"""
            if not self._check_permission(message.from_user.id):
                return

            session = self._get_session(message.from_user.id)
            keyword = (message.text or "").strip()
            session.awaiting_keyword = False

            if not keyword:
                self.bot.reply_to(message, "❌ 请输入搜索关键词", reply_markup=self._main_keyboard())
                return

            # 避免把按钮文字当关键词
            if keyword in ("🔍 搜索", "📊 状态", "🧹 整理", "📋 进度", "❓ 帮助"):
                return

            self._start_search(message, keyword)

        def _is_awaiting_subscribe(m: Message) -> bool:
            if not m or not getattr(m, "text", None) or not getattr(m, "from_user", None):
                return False
            session = self.sessions.get(m.from_user.id)
            return bool(session and session.awaiting_subscribe)

        @self.bot.message_handler(func=_is_awaiting_subscribe)
        def handle_subscribe_keyword(message: Message):
            """订阅关键词输入 -> TMDB 搜索并列出选项"""
            if not self._check_permission(message.from_user.id):
                return
            if not self.sub_mgr or not self.sub_mgr.tmdb:
                self.bot.reply_to(message, "❌ 未启用订阅功能")
                return
            session = self._get_session(message.from_user.id)
            keyword = (message.text or "").strip()
            session.awaiting_subscribe = False
            if not keyword:
                self.bot.reply_to(message, "❌ 请输入订阅关键词", reply_markup=self._main_keyboard())
                return

            # 使用统一的标准化函数
            from modules.tmdb_client import normalize_search_query

            norm = normalize_search_query(keyword)
            query = norm["query"]
            season_hint = norm["season"]

            # 先让用户选择范围（电影/电视剧/都搜），再进行 TMDB 搜索，避免范围过大/结果不准
            session.sub_query = query
            session.sub_season_hint = season_hint
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton(text="📺 电视剧", callback_data="subtype_tv"),
                InlineKeyboardButton(text="🎬 电影", callback_data="subtype_movie"),
                InlineKeyboardButton(text="🌐 都搜", callback_data="subtype_all"),
            )
            hint = f"（已识别季号 S{int(season_hint):02d}，将用于显示该季信息/仅订阅该季）" if season_hint else ""
            self.bot.reply_to(
                message,
                f"请选择订阅类型：{hint}\n关键词：<b>{self._escape_html(query)}</b>",
                reply_markup=markup,
            )
            return

        @self.bot.message_handler(commands=["search"])
        def handle_search_command(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return

            # 提取关键词
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                # 从菜单点 /search 时通常会直接发出命令，这里进入“等待关键词”模式
                self._prompt_keyword(message)
                return

            keyword = parts[1].strip()
            self._start_search(message, keyword)

        @self.bot.message_handler(func=lambda m: m.text and m.text.startswith("搜索"))
        def handle_search_text(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return

            # 提取关键词
            keyword = message.text[2:].strip()
            if not keyword:
                self.bot.reply_to(message, "❌ 请输入搜索关键词\n例如：搜索 流浪地球")
                return

            self._start_search(message, keyword)

        @self.bot.message_handler(commands=["status"])
        def handle_status(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return

            self._show_download_status(message)

        @self.bot.message_handler(commands=["organize"])
        def handle_organize(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return
            if not self.organizer:
                self.bot.reply_to(
                    message,
                    "❌ 未启用整理功能，请在 config.yaml 配置 organize.enabled=true",
                )
                return
            self._manual_organize_scan(message)

        @self.bot.message_handler(commands=["org_status"])
        def handle_org_status(message: Message):
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return
            if not self.org_store:
                self.bot.reply_to(message, "❌ 未启用整理功能")
                return
            self._show_org_status(message)

        @self.bot.message_handler(commands=["subscribe"])
        def handle_subscribe(message: Message):
            """添加订阅：/subscribe 片名 或 /subscribe tmdb_id tv|movie"""
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return
            if not self.sub_mgr or not self.sub_mgr.tmdb:
                self.bot.reply_to(message, "❌ 未启用订阅功能（缺少 TMDB 配置或未初始化）")
                return
            parts = message.text.split(maxsplit=2)
            if len(parts) >= 3 and parts[1].isdigit():
                tmdb_id = parts[1].strip()
                sub_type = parts[2].strip().lower()
                try:
                    sub_id = self.sub_mgr.add_subscription(tmdb_id=tmdb_id, sub_type=sub_type)
                    self.bot.reply_to(message, f"✅ 已添加订阅：{tmdb_id} ({sub_type})\nID: {sub_id}")
                except Exception as e:
                    self.bot.reply_to(message, f"❌ 添加订阅失败：{e}")
                return
            # 无 tmdb_id 情况：进入关键词搜索流程
            self._prompt_subscribe(message)

        @self.bot.message_handler(commands=["subs"])
        def handle_subs(message: Message):
            """查看订阅列表"""
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return
            if not self.sub_mgr:
                self.bot.reply_to(message, "❌ 未启用订阅功能")
                return
            subs = self.sub_mgr.list_subscriptions(limit=50)
            if not subs:
                self.bot.reply_to(message, "📭 当前没有订阅")
                return
            lines = ["📺 <b>订阅列表</b>\n"]
            markup = InlineKeyboardMarkup()
            for s in subs:
                sf = s.get("season_filter")
                sf_text = f" S{int(sf):02d}" if sf and int(sf) > 0 else ""
                lines.append(
                    f"• ID {s['id']}: {self._escape_html(s.get('title', '')[:40])}"
                    f"{sf_text} ({s.get('type')}) {s.get('year', '')}\n"
                    f"  下载/总：{s.get('downloaded', 0)}/{s.get('total', 0)}  "
                    f"整理：{s.get('organized', 0)}"
                )
                markup.row(
                    InlineKeyboardButton(text=f"详情 {s['id']}", callback_data=f"subinfo_{s['id']}"),
                    InlineKeyboardButton(text=f"取消 {s['id']}", callback_data=f"subdel_{s['id']}"),
                    InlineKeyboardButton(text=f"刷新 {s['id']}", callback_data=f"subrefresh_{s['id']}"),
                )
            self.bot.reply_to(message, "\n".join(lines), reply_markup=markup)

        @self.bot.message_handler(commands=["sub_status"])
        def handle_sub_status(message: Message):
            """查看订阅详情：/sub_status <id>"""
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return
            if not self.sub_mgr:
                self.bot.reply_to(message, "❌ 未启用订阅功能")
                return
            parts = message.text.split()
            if len(parts) < 2:
                self.bot.reply_to(message, "用法：/sub_status <id>")
                return
            try:
                sub_id = int(parts[1])
                sub = self.sub_mgr.store.get_subscription(sub_id)
                if not sub:
                    self.bot.reply_to(message, "未找到该订阅")
                    return
                items = self.sub_mgr.store.list_items(sub_id)
                total = len(items)
                downloaded = len([i for i in items if i.get("downloaded")])
                organized = len([i for i in items if i.get("organized")])
                lines = [
                    f"📺 <b>{self._escape_html(sub.get('title', ''))}</b> ({sub.get('type')})",
                    f"TMDB: {sub.get('tmdb_id')}  年份: {sub.get('year', '')}",
                    f"下载/总：{downloaded}/{total}  整理：{organized}",
                    "━━━━━━━━━━━━",
                ]
                show_items = items[:30]
                for it in show_items:
                    season = it.get("season")
                    ep = it.get("episode")
                    lines.append(
                        f"S{int(season):02d}E{int(ep):02d} - {self._escape_html((it.get('name') or '')[:40])} "
                        f"[下:{it.get('downloaded')} 整:{it.get('organized')}]"
                    )
                if len(items) > len(show_items):
                    lines.append(f"... 共 {total} 条")
                self.bot.reply_to(message, "\n".join(lines))
            except Exception as e:
                self.bot.reply_to(message, f"❌ 查询失败：{e}")

        @self.bot.message_handler(commands=["sub_del"])
        def handle_sub_del(message: Message):
            """删除订阅：/sub_del <id>"""
            if not self._check_permission(message.from_user.id):
                self.bot.reply_to(message, "⛔ 你没有权限使用此机器人")
                return
            if not self.sub_mgr:
                self.bot.reply_to(message, "❌ 未启用订阅功能")
                return
            parts = message.text.split()
            if len(parts) < 2:
                self.bot.reply_to(message, "用法：/sub_del <id>")
                return
            try:
                sub_id = int(parts[1])
                self.sub_mgr.delete_subscription(sub_id)
                self.bot.reply_to(message, f"🗑️ 已删除订阅 ID {sub_id}")
            except Exception as e:
                self.bot.reply_to(message, f"❌ 删除失败：{e}")

        @self.bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("subsel_"))
        def handle_sub_select(call: CallbackQuery):
            """处理 TMDB 搜索结果选择"""
            if not self._check_permission(call.from_user.id):
                return
            if not self.sub_mgr:
                self.bot.answer_callback_query(call.id, "订阅功能未启用")
                return
            try:
                parts = call.data.split("_")
                # subsel_<tmdbid>_<type>_<season>
                tmdb_id = parts[1]
                typ = parts[2]
                season = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0
                season_filter = season if (typ == "tv" and season > 0) else None
                sub_id = self.sub_mgr.add_subscription(tmdb_id=tmdb_id, sub_type=typ, season_filter=season_filter)
                self.bot.answer_callback_query(call.id, "✅ 已添加订阅")
                self.bot.edit_message_text(
                    f"✅ 已添加订阅：TMDB {tmdb_id} ({typ})"
                    + (f" S{season:02d}" if season_filter else "")
                    + f"\nID: {sub_id}",
                    call.message.chat.id,
                    call.message.message_id,
                )
            except Exception as e:
                self.bot.answer_callback_query(call.id, "❌ 失败")
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"❌ 添加订阅失败：{e}",
                        call.message.chat.id,
                        call.message.message_id,
                    )

        @self.bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("subdel_"))
        def handle_sub_delete_cb(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                return
            if not self.sub_mgr:
                self.bot.answer_callback_query(call.id, "订阅功能未启用")
                return
            try:
                sub_id = int(call.data.split("_", 1)[1])
                self.sub_mgr.delete_subscription(sub_id)
                self.bot.answer_callback_query(call.id, "✅ 已取消订阅")
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"🗑️ 已取消订阅 ID {sub_id}",
                        call.message.chat.id,
                        call.message.message_id,
                    )
            except Exception as e:
                self.bot.answer_callback_query(call.id, "❌ 失败")
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"❌ 取消订阅失败：{e}",
                        call.message.chat.id,
                        call.message.message_id,
                    )

        @self.bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("subinfo_"))
        def handle_sub_info_cb(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                return
            if not self.sub_mgr:
                self.bot.answer_callback_query(call.id, "订阅功能未启用")
                return
            try:
                sub_id = int(call.data.split("_", 1)[1])
                sub = self.sub_mgr.store.get_subscription(sub_id)
                if not sub:
                    self.bot.answer_callback_query(call.id, "未找到订阅")
                    return
                items = self.sub_mgr.store.list_items(sub_id)
                total = len(items)
                downloaded = len([i for i in items if i.get("downloaded")])
                organized = len([i for i in items if i.get("organized")])
                text = (
                    f"📺 <b>{self._escape_html(sub.get('title', ''))}</b> ({sub.get('type')})\n"
                    f"下载/总：{downloaded}/{total}  整理：{organized}\n"
                    f"TMDB: {sub.get('tmdb_id')}  年份: {sub.get('year', '')}"
                )
                self.bot.answer_callback_query(call.id)
                self.bot.edit_message_text(
                    text,
                    call.message.chat.id,
                    call.message.message_id,
                )
            except Exception as e:
                self.bot.answer_callback_query(call.id, "❌ 失败")
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"❌ 查询失败：{e}",
                        call.message.chat.id,
                        call.message.message_id,
                    )

        @self.bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("subrefresh_"))
        def handle_sub_refresh_cb(call: CallbackQuery):
            """按需刷新单个订阅的本地扫描（避免 /subs 每次都扫全库）"""
            if not self._check_permission(call.from_user.id):
                return
            if not self.sub_mgr:
                self.bot.answer_callback_query(call.id, "订阅功能未启用")
                return
            try:
                sub_id = int(call.data.split("_", 1)[1])
            except Exception:
                self.bot.answer_callback_query(call.id, "参数错误")
                return
            self.bot.answer_callback_query(call.id, "🔄 正在刷新本地进度...")
            try:
                sub = self.sub_mgr.store.get_subscription(sub_id)
                if sub:
                    if sub.get("type") == "tv":
                        self.sub_mgr._scan_local_tv(sub)
                    else:
                        self.sub_mgr._scan_local_movie(sub)
                # 重新展示详情
                sub = self.sub_mgr.store.get_subscription(sub_id) or {}
                sf = sub.get("season_filter")
                cnt = self.sub_mgr.store.get_subscription_counts(sub_id, season_filter=sf)
                title = sub.get("title", "")
                sf_text = f" S{int(sf):02d}" if sf and int(sf) > 0 else ""
                text = (
                    f"🔄 已刷新：<b>{self._escape_html(title)}</b>{sf_text}\n"
                    f"下载/总：{cnt['downloaded']}/{cnt['total']}  整理：{cnt['organized']}\n"
                    f"ID: {sub_id}"
                )
                try:
                    self.bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
                except Exception:
                    self.bot.send_message(call.message.chat.id, text)
            except Exception as e:
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"❌ 刷新失败：{e}",
                        call.message.chat.id,
                        call.message.message_id,
                    )

        @self.bot.callback_query_handler(func=lambda call: call.data in ("subtype_tv", "subtype_movie", "subtype_all"))
        def handle_sub_type_select(call: CallbackQuery):
            """订阅：选择 tv/movie/all 后再做 TMDB 搜索并展示候选"""
            if not self._check_permission(call.from_user.id):
                return
            if not self.sub_mgr or not self.sub_mgr.tmdb:
                self.bot.answer_callback_query(call.id, "订阅功能未启用")
                return
            session = self._get_session(call.from_user.id)
            query = (session.sub_query or "").strip()
            season_hint = session.sub_season_hint
            if not query:
                self.bot.answer_callback_query(call.id, "请重新 /subscribe 输入关键词")
                return

            sel = call.data.split("_", 1)[1]  # tv/movie/all

            self.bot.answer_callback_query(call.id, "🔎 TMDB 搜索中...")

            try:
                results = []

                # 根据选择的类型搜索
                if sel == "tv":
                    tv_results = self.sub_mgr.tmdb.search_tv(query)
                    for r in tv_results[:6]:
                        results.append(
                            {
                                "id": r.get("id"),
                                "type": "tv",
                                "name": r.get("name") or r.get("title") or "",
                                "original_name": r.get("original_name") or "",
                                "year": (r.get("first_air_date") or "")[:4],
                                "overview": r.get("overview") or "",
                                "poster_path": r.get("poster_path") or "",
                            }
                        )
                elif sel == "movie":
                    movie_results = self.sub_mgr.tmdb.search_movie(query)
                    for r in movie_results[:6]:
                        results.append(
                            {
                                "id": r.get("id"),
                                "type": "movie",
                                "name": r.get("title") or r.get("name") or "",
                                "original_name": r.get("original_title") or "",
                                "year": (r.get("release_date") or "")[:4],
                                "overview": r.get("overview") or "",
                                "poster_path": r.get("poster_path") or "",
                            }
                        )
                else:  # all - 搜索两种类型
                    tv_results = self.sub_mgr.tmdb.search_tv(query)
                    for r in tv_results[:3]:
                        results.append(
                            {
                                "id": r.get("id"),
                                "type": "tv",
                                "name": r.get("name") or r.get("title") or "",
                                "original_name": r.get("original_name") or "",
                                "year": (r.get("first_air_date") or "")[:4],
                                "overview": r.get("overview") or "",
                                "poster_path": r.get("poster_path") or "",
                            }
                        )
                    movie_results = self.sub_mgr.tmdb.search_movie(query)
                    for r in movie_results[:3]:
                        results.append(
                            {
                                "id": r.get("id"),
                                "type": "movie",
                                "name": r.get("title") or r.get("name") or "",
                                "original_name": r.get("original_title") or "",
                                "year": (r.get("release_date") or "")[:4],
                                "overview": r.get("overview") or "",
                                "poster_path": r.get("poster_path") or "",
                            }
                        )

            except Exception as e:
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"❌ TMDB 搜索失败：{e}",
                        call.message.chat.id,
                        call.message.message_id,
                    )
                return
            if not results:
                with contextlib.suppress(Exception):
                    self.bot.edit_message_text(
                        f"📭 未找到匹配的 TMDB 结果\n关键词：<b>{self._escape_html(query)}</b>",
                        call.message.chat.id,
                        call.message.message_id,
                    )
                return

            # 构建展示（包含原名、海报链接、overview 摘要；若带季号，补充该季信息）
            text = "📺 <b>选择要订阅的条目</b>\n\n"
            markup = InlineKeyboardMarkup()

            for idx, r in enumerate(results, start=1):
                tmdb_id = int(r.get("id"))
                typ = r.get("type", "")
                name = (r.get("name") or "").strip()
                original_name = (r.get("original_name") or "").strip()
                year = r.get("year", "")
                overview = (r.get("overview") or "").strip()
                poster_path = r.get("poster_path") or ""
                poster_url = self.sub_mgr.tmdb.build_image_url(poster_path, original=False) if poster_path else ""

                # 如果是 tv，尽量用 tv_detail 的 cn/en 标题（更接近 MoviePilot 的展示效果）
                cn_title = ""
                en_title = ""
                season_line = ""
                if typ == "tv":
                    try:
                        d = self.sub_mgr.tmdb.tv_detail(tmdb_id)
                        cn_title, en_title = self.sub_mgr.tmdb.extract_titles(d, is_movie=False)
                        # season info
                        if season_hint:
                            for s in d.get("seasons") or []:
                                if int(s.get("season_number", -1)) == int(season_hint):
                                    sname = s.get("name") or f"Season {season_hint}"
                                    epc = s.get("episode_count") or ""
                                    air = s.get("air_date") or ""
                                    s_over = (s.get("overview") or "").strip()
                                    season_line = (
                                        f"  ├ 季：S{int(season_hint):02d} "
                                        f"{self._escape_html(sname)} | 集数：{epc} | 首播：{air}\n"
                                    )
                                    if s_over:
                                        over_short = self._escape_html(s_over[:80])
                                        ellipsis = "..." if len(s_over) > 80 else ""
                                        season_line += f"  ├ 简介：{over_short}{ellipsis}\n"
                                    break
                    except Exception:
                        pass

                # 标题展示：优先 cn_title，其次 name；并展示原名（若不同）
                display = cn_title or name or original_name
                if not display:
                    display = str(tmdb_id)
                alt = ""
                alt_src = en_title or original_name
                if alt_src and alt_src != display:
                    alt = f"（{self._escape_html(alt_src)}）"

                text += f"{idx}. <b>{self._escape_html(display)}</b> {alt} ({year}) [{typ}]\n"
                if season_line:
                    text += season_line
                if overview:
                    text += f"  ├ 简介：{self._escape_html(overview[:80])}{'...' if len(overview) > 80 else ''}\n"
                if poster_url:
                    text += f"  └ 海报：{poster_url}\n"
                text += "\n"

                sh = int(season_hint or 0)
                cb = f"subsel_{tmdb_id}_{typ}_{sh}"
                btn_title = display[:18] if display else str(tmdb_id)
                markup.row(InlineKeyboardButton(text=f"{idx}. {btn_title} ({year})", callback_data=cb))

            if season_hint:
                text += f"🔖 已识别季号：S{int(season_hint):02d}（将仅订阅该季）"

            try:
                self.bot.edit_message_text(
                    text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    disable_web_page_preview=False,
                )
            except Exception:
                with contextlib.suppress(Exception):
                    self.bot.send_message(
                        call.message.chat.id,
                        text,
                        reply_markup=markup,
                        disable_web_page_preview=False,
                    )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
        def handle_category_selection(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                self.bot.answer_callback_query(call.id, "⛔ 没有权限")
                return

            category = call.data[4:]  # 去掉 "cat_" 前缀
            self._do_search(call, category)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
        def handle_download(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                self.bot.answer_callback_query(call.id, "⛔ 没有权限")
                return

            torrent_id = call.data[3:]  # 去掉 "dl_" 前缀
            logger.info(f"[DEBUG] handle_download callback: call.data={call.data}, torrent_id={torrent_id}")
            self._do_download(call, torrent_id)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("page_"))
        def handle_pagination(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                self.bot.answer_callback_query(call.id, "⛔ 没有权限")
                return

            page = int(call.data[5:])  # 去掉 "page_" 前缀
            self._show_page(call, page)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("qcat_"))
        def handle_qbit_category_selection(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                self.bot.answer_callback_query(call.id, "⛔ 没有权限")
                return

            # qcat_<category> 或 qcat_ (无分类)
            qbit_category = call.data[5:]  # 去掉 "qcat_" 前缀
            if qbit_category == "__none__":
                qbit_category = None
            self._execute_download(call, qbit_category)

        @self.bot.callback_query_handler(func=lambda call: call.data == "cancel")
        def handle_cancel(call: CallbackQuery):
            session = self._get_session(call.from_user.id)
            session.keyword = None
            session.results = []
            session.pending_torrent_id = None

            self.bot.edit_message_text("❌ 已取消", call.message.chat.id, call.message.message_id)
            self.bot.answer_callback_query(call.id)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("org_"))
        def handle_org_action(call: CallbackQuery):
            if not self._check_permission(call.from_user.id):
                self.bot.answer_callback_query(call.id, "⛔ 没有权限")
                return
            if not self.organizer:
                self.bot.answer_callback_query(call.id, "❌ 未启用整理功能")
                return
            # org_<hash>
            torrent_hash = call.data.split("_", 1)[1]
            self._manual_organize_execute(call, torrent_hash)

    def _start_search(self, message: Message, keyword: str):
        """开始搜索流程：显示类别选择"""
        session = self._get_session(message.from_user.id)
        session.keyword = keyword
        session.page = 1
        session.results = []

        # 创建类别选择按钮
        categories = self.mteam.get_category_list()
        markup = InlineKeyboardMarkup(row_width=2)

        buttons = []
        for key, name in categories.items():
            buttons.append(InlineKeyboardButton(text=name, callback_data=f"cat_{key}"))

        # 添加按钮（每行2个）
        for i in range(0, len(buttons), 2):
            row = buttons[i : i + 2]
            markup.row(*row)

        # 添加取消按钮
        markup.row(InlineKeyboardButton(text="❌ 取消", callback_data="cancel"))

        msg = self.bot.reply_to(
            message,
            f"🔍 搜索：<b>{self._escape_html(keyword)}</b>\n\n请选择搜索类别：",
            reply_markup=markup,
        )
        session.message_id = msg.message_id

    def _do_search(self, call: CallbackQuery, category: str):
        """执行搜索"""
        session = self._get_session(call.from_user.id)
        session.category = category

        if not session.keyword:
            self.bot.answer_callback_query(call.id, "❌ 会话已过期，请重新搜索")
            return

        self.bot.answer_callback_query(call.id, "🔍 搜索中...")

        # 更新消息显示搜索中
        category_name = self.mteam.categories.get(category, {}).get("name", category)
        self.bot.edit_message_text(
            f"🔍 正在搜索：<b>{self._escape_html(session.keyword)}</b>\n📂 类别：{category_name}\n\n⏳ 请稍候...",
            call.message.chat.id,
            call.message.message_id,
        )

        try:
            results = self.mteam.search(session.keyword, category, page=1)
            session.results = results
            session.page = 1

            if not results:
                self.bot.edit_message_text(
                    f"🔍 搜索：<b>{self._escape_html(session.keyword)}</b>\n"
                    f"📂 类别：{category_name}\n\n"
                    "😔 未找到相关资源",
                    call.message.chat.id,
                    call.message.message_id,
                )
                return

            self._show_results(call.message.chat.id, call.message.message_id, session)

        except MTeamAPIError as e:
            self.bot.edit_message_text(f"❌ 搜索失败：{e!s}", call.message.chat.id, call.message.message_id)

    def _show_results(self, chat_id: int, message_id: int, session: UserSession):
        """显示搜索结果"""
        results = session.results
        page = session.page
        page_size = 5

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_results = results[start_idx:end_idx]

        total_pages = (len(results) + page_size - 1) // page_size

        # 构建消息
        category_name = self.mteam.categories.get(session.category, {}).get("name", session.category)
        text = (
            f"🔍 搜索：<b>{self._escape_html(session.keyword)}</b>\n"
            f"📂 类别：{category_name}\n"
            f"📊 找到 {len(results)} 个结果（第 {page}/{total_pages} 页）\n\n"
        )

        # 创建结果按钮
        markup = InlineKeyboardMarkup()

        for idx, torrent in enumerate(page_results, start=start_idx + 1):
            # 添加详情到消息
            title = torrent.name
            if len(title) > 90:
                title = title[:90] + "..."

            # 标签：字幕/清晰度/HDR 等（来自 labelsNew + 标题推断）
            tags = torrent.tag_list_compact
            tags_text = f"🏷️ {self._escape_html(tags)}\n" if tags else ""

            # 评分：豆瓣/IMDb（如果有）
            rating_parts = []
            if torrent.douban_rating:
                if torrent.douban_url:
                    rating_parts.append(
                        f'豆瓣 <a href="{torrent.douban_url}">{self._escape_html(torrent.douban_rating)}</a>'
                    )
                else:
                    rating_parts.append(f"豆瓣 {self._escape_html(torrent.douban_rating)}")
            if torrent.imdb_rating:
                if torrent.imdb_url:
                    rating_parts.append(
                        f'IMDb <a href="{torrent.imdb_url}">{self._escape_html(torrent.imdb_rating)}</a>'
                    )
                else:
                    rating_parts.append(f"IMDb {self._escape_html(torrent.imdb_rating)}")
            rating_text = f"⭐ {' | '.join(rating_parts)}\n" if rating_parts else ""

            # 简介（smallDescr）可选显示一行，避免太长
            descr = (torrent.small_descr or "").strip()
            if descr:
                if len(descr) > 60:
                    descr = descr[:60] + "..."
                descr_text = f"📝 <i>{self._escape_html(descr)}</i>\n"
            else:
                descr_text = ""

            text += (
                f"<b>{idx}.</b> {self._escape_html(title)}\n"
                f"{descr_text}"
                f"{tags_text}"
                f"{rating_text}"
                f"📦 {torrent.size}  ⬆️ {torrent.seeders}  ⬇️ {torrent.leechers}\n\n"
            )

            # 按钮文案尽量短：编号 + 清晰度/字幕 + 大小 + 做种
            btn_tags = torrent.tag_resolution or ""
            if torrent.tag_subtitle:
                btn_tags = f"{torrent.tag_subtitle} {btn_tags}".strip()
            btn_prefix = f"{btn_tags} " if btn_tags else ""
            markup.row(
                InlineKeyboardButton(
                    text=f"⬇️ {idx}. {btn_prefix}{torrent.size} ↑{torrent.seeders}",
                    callback_data=f"dl_{torrent.id}",
                )
            )

        # 分页按钮
        page_buttons = []
        if page > 1:
            page_buttons.append(InlineKeyboardButton(text="⬅️ 上一页", callback_data=f"page_{page - 1}"))
        if page < total_pages:
            page_buttons.append(InlineKeyboardButton(text="下一页 ➡️", callback_data=f"page_{page + 1}"))

        if page_buttons:
            markup.row(*page_buttons)

        # 取消按钮
        markup.row(InlineKeyboardButton(text="❌ 取消", callback_data="cancel"))

        self.bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)

    def _show_page(self, call: CallbackQuery, page: int):
        """显示指定页"""
        session = self._get_session(call.from_user.id)

        if not session.results:
            self.bot.answer_callback_query(call.id, "❌ 会话已过期，请重新搜索")
            return

        session.page = page
        self.bot.answer_callback_query(call.id)
        self._show_results(call.message.chat.id, call.message.message_id, session)

    def _do_download(self, call: CallbackQuery, torrent_id: str):
        """处理下载请求：显示 qBit 分类选择"""
        logger.info(f"[DEBUG] _do_download 收到 torrent_id={torrent_id}, type={type(torrent_id)}")

        session = self._get_session(call.from_user.id)
        session.pending_torrent_id = torrent_id

        logger.info(f"[DEBUG] session.results 数量: {len(session.results)}")
        if session.results:
            logger.info(f"[DEBUG] 第一个结果 id={session.results[0].id}, type={type(session.results[0].id)}")

        # 查找种子信息
        torrent = next((t for t in session.results if t.id == torrent_id), None)
        logger.info(f"[DEBUG] 查找到的 torrent: {torrent}")
        torrent_name = torrent.name if torrent else f"ID: {torrent_id}"

        # 获取 qBittorrent 中的分类列表
        categories = self.qbit.get_categories()

        self.bot.answer_callback_query(call.id)

        # 显示分类选择按钮
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = []

        for cat_name in categories:
            buttons.append(InlineKeyboardButton(text=f"📂 {cat_name}", callback_data=f"qcat_{cat_name}"))

        # 添加按钮（每行2个）
        for i in range(0, len(buttons), 2):
            row = buttons[i : i + 2]
            markup.row(*row)

        # 添加"使用默认路径"和取消按钮
        default_path = self.config.download.get("default_path", "")
        default_btn_text = "📁 默认路径" if default_path else "📁 不指定路径"
        markup.row(InlineKeyboardButton(text=default_btn_text, callback_data="qcat___none__"))
        markup.row(InlineKeyboardButton(text="❌ 取消", callback_data="cancel"))

        self.bot.edit_message_text(
            f"📄 <b>{self._escape_html(torrent_name[:60])}</b>\n\n请选择下载分类：",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
        )

    def _execute_download(self, call: CallbackQuery, category: str | None):
        """执行实际下载"""
        session = self._get_session(call.from_user.id)
        torrent_id = session.pending_torrent_id

        if not torrent_id:
            self.bot.answer_callback_query(call.id, "❌ 会话已过期，请重新搜索")
            return

        # 查找种子信息
        torrent = next((t for t in session.results if t.id == torrent_id), None)
        torrent_name = torrent.name if torrent else f"ID: {torrent_id}"

        self.bot.answer_callback_query(call.id, "⏳ 正在添加下载...")

        try:
            # 获取下载链接
            logger.info(f"[DEBUG] 开始获取下载链接, torrent_id={torrent_id}, type={type(torrent_id)}")
            download_url = self.mteam.get_download_url(torrent_id)
            logger.info(f"[DEBUG] 获取下载链接成功: {download_url[:50]}...")

            # 下载 torrent 文件内容（由本程序下载，再上传到 qB，避免 qB 服务器无法访问 M-Team）
            torrent_bytes, torrent_filename = self.mteam.download_torrent_file(download_url)
            logger.info(f"[DEBUG] torrent 文件已下载: {torrent_filename}, bytes={len(torrent_bytes)}")

            # 确定保存路径
            save_path = None
            if not category:
                # 未选择分类时使用默认路径
                save_path = self.config.download.get("default_path")

            # 添加到 qBittorrent
            torrent_hash = self.qbit.add_torrent(content=torrent_bytes, save_path=save_path, category=category)

            # 记录下载（用于自动整理模式过滤）
            if self.org_store and torrent_hash:
                from .store import DownloadRecord

                self.org_store.add_download(
                    DownloadRecord(
                        torrent_hash=torrent_hash,
                        torrent_name=torrent_name,
                        category=category or "",
                        mteam_id=torrent_id,
                        organized=False,
                    )
                )
                logger.info(f"[download] 已记录下载: hash={torrent_hash} name={torrent_name}")

            # 成功消息
            success_text = f"✅ <b>下载已添加</b>\n\n📄 {self._escape_html(torrent_name)}\n"
            if category:
                success_text += f"📂 分类：{category}\n"
            elif save_path:
                success_text += f"📁 路径：{save_path}\n"
            if torrent_hash and torrent_hash != "unknown":
                success_text += f"🔎 Hash：<code>{torrent_hash}</code>\n"

            self.bot.edit_message_text(success_text, call.message.chat.id, call.message.message_id)

            # 清理会话
            session.pending_torrent_id = None
            logger.info(f"下载已添加: {torrent_name} -> {torrent_hash}")

        except MTeamAPIError as e:
            self.bot.edit_message_text(
                f"❌ 获取下载链接失败：{e!s}",
                call.message.chat.id,
                call.message.message_id,
            )
        except QBitError as e:
            self.bot.edit_message_text(
                f"❌ 添加下载失败：{e!s}",
                call.message.chat.id,
                call.message.message_id,
            )

    def _show_download_status(self, message: Message):
        """显示下载状态"""
        try:
            torrents = self.qbit.get_torrents(limit=10)

            if not torrents:
                self.bot.reply_to(message, "📭 当前没有下载任务")
                return

            text = "📊 <b>下载状态</b>\n\n"

            for t in torrents:
                name = t.name[:35] + "..." if len(t.name) > 35 else t.name
                text += f"<b>{self._escape_html(name)}</b>\n   {t.state_display} | {t.progress_percent}\n\n"

            self.bot.reply_to(message, text)

        except QBitError as e:
            self.bot.reply_to(message, f"❌ 获取状态失败：{e!s}")

    def _manual_organize_scan(self, message: Message):
        """
        手动扫描：列出已完成任务，点按钮执行整理复制
        """
        try:
            torrents = self.qbit.get_torrents_by_status(status_filter="completed", limit=10)
            if not torrents:
                self.bot.reply_to(message, "📭 没有已完成任务")
                return
            markup = InlineKeyboardMarkup()
            text = "🧹 <b>已完成任务（点选整理复制到 NAS）</b>\n\n"
            for idx, t in enumerate(torrents, start=1):
                h = t.get("hash") or t.get("infohash_v1") or ""
                name = t.get("name") or ""
                if not h:
                    continue
                short = name[:50] + "..." if len(name) > 50 else name
                text += f"{idx}. {self._escape_html(short)}\n"
                # 按钮不展示 hash（人看不懂），但 callback_data 仍带 hash 用于定位任务
                markup.row(InlineKeyboardButton(text=f"整理：{idx}", callback_data=f"org_{h}"))
            self.bot.reply_to(message, text, reply_markup=markup)
        except Exception as e:
            self.bot.reply_to(message, f"❌ 扫描失败：{e}")

    def _manual_organize_execute(self, call: CallbackQuery, torrent_hash: str):
        """
        执行整理：读取该任务文件清单并复制
        """
        self.bot.answer_callback_query(call.id, "✅ 已开始整理（后台执行）")
        # 先给一个"已开始"的可见反馈，避免 Telegram 回调超时
        with contextlib.suppress(Exception):
            self.bot.edit_message_text(
                f"⏳ 已开始整理（后台执行），完成后会通知你。\nHash: <code>{torrent_hash}</code>",
                call.message.chat.id,
                call.message.message_id,
            )

        chat_id = call.message.chat.id
        if not self.org_queue:
            self.bot.send_message(chat_id, "❌ 整理队列未初始化")
            return

        tinfo = self.qbit.get_torrent_info(torrent_hash) or {}
        torrent_name = tinfo.get("name") or torrent_hash
        files = self.qbit.get_torrent_files(torrent_hash)
        base_path = tinfo.get("save_path") or tinfo.get("content_path") or ""

        def _runner():
            if not base_path:
                raise RuntimeError("无法获取下载路径(save_path/content_path)")
            torrent_ctx = {
                "name": torrent_name,
                "small_descr": "",
                "labels_new": [],
                "imdb_url": "",
            }
            return self.organizer.copy_to_library(
                torrent_hash=torrent_hash,
                base_path=base_path,
                files=files,
                torrent_info=torrent_ctx,
            )

        def _on_complete(task_id: str, mode: str, name: str, result):
            """整理完成回调：发送通知"""
            self._send_organize_notification(chat_id, task_id, mode, name, result)

        task_id = self.org_queue.submit(
            mode="manual",
            torrent_hash=torrent_hash,
            torrent_name=torrent_name,
            runner=_runner,
            on_complete=_on_complete,
        )
        self.bot.send_message(
            chat_id,
            f"🧾 已加入整理队列：{self._escape_html(torrent_name[:80])}\nTask: <code>{task_id}</code>",
        )

    def _send_organize_notification(self, chat_id: int, task_id: str, mode: str, torrent_name: str, result):
        """
        发送整理完成通知（参考 MoviePilot 的通知格式）
        """
        from .organize_queue import OrganizeResult

        if not isinstance(result, OrganizeResult):
            return

        # 构建通知消息
        short_name = torrent_name[:60] + "..." if len(torrent_name) > 60 else torrent_name

        if result.error:
            # 失败通知
            text = (
                f"❌ <b>整理失败</b>\n\n"
                f"📺 <b>{self._escape_html(short_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🚫 错误：{self._escape_html(result.error[:200])}\n"
                f"📋 Task: <code>{task_id}</code>\n"
                f"🔧 模式：{mode}"
            )
        elif result.bad > 0:
            # 部分失败
            text = (
                f"⚠️ <b>整理部分完成</b>\n\n"
                f"📺 <b>{self._escape_html(short_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ 成功：{result.ok} 个文件\n"
                f"⏭️ 跳过：{result.skipped} 个文件\n"
                f"❌ 失败：{result.bad} 个文件\n"
                f"📊 共计：{result.total} 个文件\n"
            )
            if result.dest_dir:
                text += f"📁 目录：<code>{self._escape_html(result.dest_dir)}</code>\n"
            text += f"━━━━━━━━━━━━━━━━━━\n📋 Task: <code>{task_id}</code>\n🔧 模式：{mode}"
        elif result.ok > 0:
            # 全部成功
            text = (
                f"✅ <b>整理完成</b>\n\n"
                f"📺 <b>{self._escape_html(short_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ 成功：{result.ok} 个文件\n"
            )
            if result.skipped > 0:
                text += f"⏭️ 跳过：{result.skipped} 个文件（已存在）\n"
            text += f"📊 共计：{result.total} 个文件\n"
            if result.dest_dir:
                text += f"📁 目录：<code>{self._escape_html(result.dest_dir)}</code>\n"
            text += f"━━━━━━━━━━━━━━━━━━\n📋 Task: <code>{task_id}</code>\n🔧 模式：{mode}"
        elif result.skipped > 0:
            # 全部跳过（已存在）
            text = (
                f"⏭️ <b>整理跳过（已存在）</b>\n\n"
                f"📺 <b>{self._escape_html(short_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏭️ 跳过：{result.skipped} 个文件\n"
                f"📊 共计：{result.total} 个文件\n"
            )
            if result.dest_dir:
                text += f"📁 目录：<code>{self._escape_html(result.dest_dir)}</code>\n"
            text += f"━━━━━━━━━━━━━━━━━━\n📋 Task: <code>{task_id}</code>\n🔧 模式：{mode}"
        else:
            # 没有文件需要处理
            text = (
                f"📭 <b>无文件需要整理</b>\n\n"
                f"📺 <b>{self._escape_html(short_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 共计：{result.total} 个文件\n"
                f"📋 Task: <code>{task_id}</code>\n"
                f"🔧 模式：{mode}"
            )

        try:
            self.bot.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"发送整理通知失败: {e}")

    def _show_org_status(self, message: Message):
        tasks = self.org_store.list_tasks(limit=15)
        if not tasks:
            self.bot.reply_to(message, "📭 暂无整理任务记录")
            return
        lines = ["🧹 <b>整理进度（最近 15 条）</b>\n"]
        for t in tasks:
            name = t.get("torrent_name") or t.get("torrent_hash", "")[:8]
            status = t.get("status")
            mode = t.get("mode")
            msg = t.get("message") or ""
            # 状态图标
            status_icon = {
                "queued": "⏳",
                "running": "🔄",
                "success": "✅",
                "failed": "❌",
            }.get(status, "❓")
            lines.append(f"• {status_icon} <b>{self._escape_html(name[:50])}</b>")
            lines.append(f"  状态：<code>{status}</code> | 模式：<code>{mode}</code>")
            if msg:
                lines.append(f"  {self._escape_html(msg[:150])}")
            lines.append(f"  Task: <code>{t.get('task_id')}</code>")
        self.bot.reply_to(message, "\n".join(lines))

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def start_polling(self):
        """启动长轮询"""
        logger.info("🤖 Telegram Bot 启动...")
        print("🤖 Telegram Bot 启动...")

        try:
            self.bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot 运行错误: {e}")
            raise

    def stop(self):
        """停止 Bot"""
        self.bot.stop_polling()
