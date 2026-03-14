"""
qBittorrent API 封装模块
实现种子添加和任务管理
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import qbittorrentapi

logger = logging.getLogger(__name__)


@dataclass
class TorrentStatus:
    """种子状态信息"""

    hash: str
    name: str
    state: str
    progress: float
    size: int
    downloaded: int
    uploaded: int
    dlspeed: int
    upspeed: int
    eta: int
    category: str
    save_path: str

    @property
    def progress_percent(self) -> str:
        """进度百分比"""
        return f"{self.progress * 100:.1f}%"

    @property
    def state_code(self) -> str:
        """qBittorrent 原始状态码"""
        return self.state or "unknown"

    @property
    def state_text(self) -> str:
        """状态中文文案（无 emoji）"""
        state_map = {
            "downloading": "下载中",
            "forcedDL": "强制下载",
            "metaDL": "获取元数据",
            "forcedMetaDL": "强制获取元数据",
            "stalledDL": "等待下载",
            "uploading": "做种中",
            "forcedUP": "强制做种",
            "stalledUP": "做种中",
            "pausedDL": "暂停下载",
            "pausedUP": "暂停做种",
            "stoppedDL": "暂停下载",
            "stoppedUP": "暂停做种",
            "queuedDL": "排队下载",
            "queuedUP": "排队做种",
            "queuedForChecking": "排队校验",
            "checkingDL": "校验中",
            "checkingUP": "校验中",
            "checkingResumeData": "校验中",
            "moving": "移动中",
            "allocating": "预分配中",
            "error": "错误",
            "missingFiles": "文件丢失",
            "unknown": "未知",
        }
        return state_map.get(self.state_code, self.state_code)

    @property
    def state_display(self) -> str:
        """兼容旧字段：等同 state_text"""
        return self.state_text


class QBitClient:
    """qBittorrent 客户端"""

    def __init__(self, host: str, port: int, username: str, password: str):
        """
        初始化 qBittorrent 客户端

        :param host: qBittorrent WebUI 地址
        :param port: 端口号
        :param username: 用户名
        :param password: 密码
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self._client: qbittorrentapi.Client | None = None

    @property
    def client(self) -> qbittorrentapi.Client:
        """获取已连接的客户端"""
        if self._client is None:
            self._connect()
        return self._client

    def _connect(self):
        """连接到 qBittorrent"""
        try:
            # 处理 host 格式
            host = self.host.rstrip("/")
            if not host.startswith("http"):
                host = f"http://{host}"

            self._client = qbittorrentapi.Client(
                host=f"{host}:{self.port}",
                username=self.username,
                password=self.password,
                VERIFY_WEBUI_CERTIFICATE=False,
                REQUESTS_ARGS={"timeout": (15, 60)},
            )
            self._client.auth_log_in()
        except qbittorrentapi.LoginFailed:
            raise QBitError("qBittorrent 登录失败：用户名或密码错误")
        except Exception as e:
            raise QBitError(f"qBittorrent 连接失败：{e!s}")

    def add_torrent(
        self,
        content: str | bytes,
        save_path: str | None = None,
        category: str | None = None,
        paused: bool = False,
    ) -> str:
        """
        添加种子下载任务

        :param content: 种子下载链接/magnet（str）或 torrent 文件内容（bytes）
        :param save_path: 保存路径
        :param category: 分类
        :param paused: 是否暂停添加
        :return: 种子 hash
        """
        try:
            # 先抓取当前已有任务的 hash 集合（避免“取最新一条”误判）
            pre_torrents = []
            try:
                pre_torrents = self.client.torrents_info(sort="added_on", reverse=True, limit=200) or []
            except Exception as e:
                logger.warning(f"[DEBUG] qbit.torrents_info(pre) 失败: {e}")
                pre_torrents = []

            pre_hashes = {t.hash for t in pre_torrents if getattr(t, "hash", None)}
            logger.info(f"[DEBUG] qbit.add_torrent pre_hashes={len(pre_hashes)}")

            # 准备参数
            add_kwargs: dict[str, Any] = {
                "is_paused": paused,
            }

            if save_path:
                add_kwargs["save_path"] = save_path
                add_kwargs["use_auto_torrent_management"] = False

            if category:
                add_kwargs["category"] = category
                # 关键：让 qB 按“分类”自动套用保存路径（与 WebUI 行为一致）
                # 当未显式指定 save_path 时，强制开启 AutoTMM
                if not save_path:
                    add_kwargs["use_auto_torrent_management"] = True

            # 选择 urls / torrent_files
            if isinstance(content, bytes | bytearray):
                add_kwargs["torrent_files"] = bytes(content)
                add_kwargs.pop("urls", None)
                logger.info(
                    "[DEBUG] qbit.torrents_add request(file upload): "
                    f"host={self.host}:{self.port}, category={category}, save_path={save_path}, paused={paused}, "
                    f"bytes={len(content)}"
                )
            else:
                add_kwargs["urls"] = content
                logger.info(
                    "[DEBUG] qbit.torrents_add request(url): "
                    f"host={self.host}:{self.port}, category={category}, save_path={save_path}, paused={paused}, "
                    f"url={str(content)[:120]}{'...' if len(str(content)) > 120 else ''}"
                )

            result = self.client.torrents_add(**add_kwargs)
            logger.info(f"[DEBUG] qbit.torrents_add response: {result!r}")

            # qBittorrent 返回一般为 "Ok."，失败可能为 "Fails." 或错误字符串
            if not result or "Ok" not in str(result):
                raise QBitError(f"添加种子失败: {result}")

            # 关键：不要依赖 added_on 与本机时间（可能存在时钟偏差），改为集合差集确认“新 hash 出现”
            deadline = time.time() + 10
            last_seen = pre_torrents
            while time.time() < deadline:
                torrents = self.client.torrents_info(sort="added_on", reverse=True, limit=20)
                last_seen = torrents or []

                post_hashes = {t.hash for t in last_seen if getattr(t, "hash", None)}
                new_hashes = list(post_hashes - pre_hashes)
                if new_hashes:
                    # 如出现多个（并发/自动订阅等），优先选 added_on 最大的那个
                    new_torrents = [t for t in last_seen if t.hash in new_hashes]
                    new_torrents.sort(key=lambda x: int(getattr(x, "added_on", 0) or 0), reverse=True)
                    chosen = new_torrents[0]
                    logger.info(
                        "[DEBUG] qbit.add_torrent detected new torrent: "
                        f"hash={chosen.hash}, name={getattr(chosen, 'name', '')}, "
                        f"category={getattr(chosen, 'category', '')}, save_path={getattr(chosen, 'save_path', '')}, "
                        f"state={getattr(chosen, 'state', '')}"
                    )
                    return chosen.hash

                time.sleep(0.5)

            # 轮询超时仍未发现，明确报错（而不是返回 unknown 或旧 hash）
            try:
                recent = self.client.torrents_info(sort="added_on", reverse=True, limit=5) or []
                recent_brief = [
                    {
                        "hash": t.hash,
                        "name": getattr(t, "name", ""),
                        "added_on": getattr(t, "added_on", ""),
                        "state": getattr(t, "state", ""),
                    }
                    for t in recent
                ]
                logger.info(f"[DEBUG] qbit recent torrents(top5): {recent_brief}")
            except Exception as e:
                logger.warning(f"[DEBUG] qbit.torrents_info(recent) 失败: {e}")

            raise QBitError(
                "已收到 qBittorrent 的 Ok 响应，但 10 秒内未查询到新任务。"
                "可能原因：qB 端无法访问该下载 URL、被“拒绝重复任务”等设置拦截、或你在 UI 中使用了过滤条件没显示。"
            )

        except qbittorrentapi.APIConnectionError as e:
            raise QBitError(f"连接 qBittorrent 失败：{e!s}")
        except Exception as e:
            if "QBitError" in str(type(e)):
                raise
            raise QBitError(f"添加种子失败：{e!s}")

    def get_torrent(self, torrent_hash: str) -> TorrentStatus | None:
        """
        获取种子状态

        :param torrent_hash: 种子 hash
        :return: TorrentStatus 或 None
        """
        try:
            torrents = self.client.torrents_info(torrent_hashes=torrent_hash)
            if torrents:
                t = torrents[0]
                return TorrentStatus(
                    hash=t.hash,
                    name=t.name,
                    state=t.state,
                    progress=t.progress,
                    size=t.size,
                    downloaded=t.downloaded,
                    uploaded=t.uploaded,
                    dlspeed=t.dlspeed,
                    upspeed=t.upspeed,
                    eta=t.eta,
                    category=t.category,
                    save_path=t.save_path,
                )
            return None
        except Exception:
            return None

    def get_torrents(
        self,
        category: str | None = None,
        limit: int = 10,
    ) -> list[TorrentStatus]:
        """
        获取种子列表（简单版，向后兼容）

        :param category: 筛选分类
        :param limit: 返回数量
        :return: TorrentStatus 列表
        """
        try:
            kwargs: dict[str, Any] = {
                "sort": "added_on",
                "reverse": True,
                "limit": limit,
            }
            if category:
                kwargs["category"] = category

            torrents = self.client.torrents_info(**kwargs)

            return [
                TorrentStatus(
                    hash=t.hash,
                    name=t.name,
                    state=t.state,
                    progress=t.progress,
                    size=t.size,
                    downloaded=t.downloaded,
                    uploaded=t.uploaded,
                    dlspeed=t.dlspeed,
                    upspeed=t.upspeed,
                    eta=t.eta,
                    category=t.category,
                    save_path=t.save_path,
                )
                for t in torrents
            ]
        except Exception:
            return []

    def get_torrents_paged(
        self,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
        filter_text: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[TorrentStatus], int]:
        """
        获取种子列表（带分页和搜索）

        :param category: 筛选分类
        :param limit: 返回数量
        :param offset: 偏移量（分页）
        :param filter_text: 模糊搜索文本
        :param status_filter: 状态过滤 (downloading, completed, paused, etc.)
        :return: (TorrentStatus 列表, 总数)
        """
        try:
            kwargs: dict[str, Any] = {"sort": "added_on", "reverse": True}
            if category:
                kwargs["category"] = category
            if status_filter:
                # qbittorrent-api 版本差异处理
                try:
                    torrents = self.client.torrents_info(**kwargs, status_filter=status_filter)
                except TypeError:
                    torrents = self.client.torrents_info(**kwargs, filter=status_filter)
            else:
                torrents = self.client.torrents_info(**kwargs)

            # 模糊搜索过滤
            if filter_text:
                filter_lower = filter_text.lower()
                torrents = [t for t in torrents if filter_lower in t.name.lower()]

            # 分页处理
            total = len(torrents)
            torrents = torrents[offset : offset + limit]

            return [
                TorrentStatus(
                    hash=t.hash,
                    name=t.name,
                    state=t.state,
                    progress=t.progress,
                    size=t.size,
                    downloaded=t.downloaded,
                    uploaded=t.uploaded,
                    dlspeed=t.dlspeed,
                    upspeed=t.upspeed,
                    eta=t.eta,
                    category=t.category,
                    save_path=t.save_path,
                )
                for t in torrents
            ], total
        except Exception:
            return [], 0

    def pause_torrent(self, torrent_hash: str) -> bool:
        """暂停种子"""
        try:
            self.client.torrents_pause(torrent_hashes=torrent_hash)
            return True
        except Exception as e:
            raise QBitError(f"暂停任务失败: {e!s}")

    def resume_torrent(self, torrent_hash: str) -> bool:
        """恢复种子"""
        try:
            self.client.torrents_resume(torrent_hashes=torrent_hash)
            return True
        except Exception as e:
            raise QBitError(f"恢复任务失败: {e!s}")

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        """删除种子"""
        try:
            self.client.torrents_delete(torrent_hashes=torrent_hash, delete_files=delete_files)
            return True
        except Exception as e:
            raise QBitError(f"删除任务失败: {e!s}")

    def test_connection(self) -> bool:
        """
        测试连接

        :return: 连接是否成功
        """
        try:
            self.client.app_version()
            return True
        except Exception:
            return False

    def get_version(self) -> str:
        """获取 qBittorrent 版本"""
        try:
            return self.client.app_version()
        except Exception:
            return "unknown"

    def get_categories(self) -> dict[str, str]:
        """
        获取 qBittorrent 中已创建的分类列表

        :return: {分类名称: 保存路径}
        """
        try:
            categories = self.client.torrents_categories()
            return {name: info.get("savePath", "") for name, info in categories.items()}
        except Exception:
            return {}

    def get_torrents_by_status(self, status_filter: str = "completed", limit: int = 50) -> list[dict[str, Any]]:
        """
        获取指定状态的任务列表（用于整理模块）
        status_filter 常见：completed, downloading, paused, active 等
        """
        try:
            # qbittorrent-api 版本差异：有的用 status_filter，有的用 filter
            try:
                torrents = self.client.torrents_info(
                    status_filter=status_filter,
                    sort="added_on",
                    reverse=True,
                    limit=limit,
                )
            except TypeError:
                torrents = self.client.torrents_info(filter=status_filter, sort="added_on", reverse=True, limit=limit)
            return [t.to_dict() if hasattr(t, "to_dict") else dict(t) for t in torrents]
        except Exception:
            return []

    def get_torrent_files(self, torrent_hash: str) -> list[dict[str, Any]]:
        """
        获取任务文件清单
        """
        try:
            files = self.client.torrents_files(torrent_hash=torrent_hash)
            return [f.to_dict() if hasattr(f, "to_dict") else dict(f) for f in files]
        except Exception:
            return []

    def get_torrent_info(self, torrent_hash: str) -> dict[str, Any]:
        """
        获取单个任务信息（用于手动整理，不依赖 filter=all）
        """
        try:
            try:
                torrents = self.client.torrents_info(torrent_hashes=torrent_hash)
            except TypeError:
                torrents = self.client.torrents_info(hashes=torrent_hash)
            if not torrents:
                return {}
            t = torrents[0]
            return t.to_dict() if hasattr(t, "to_dict") else dict(t)
        except Exception:
            return {}


class QBitError(Exception):
    """qBittorrent 错误"""

    pass
