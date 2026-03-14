"""
订阅与自动更新下载
- 支持 movie/tv 订阅
- 定时轮询 TMDB -> PT站点 搜索 -> qB 添加任务
- 支持多 PT 站点扩展
- 基于 Store 记录订阅与条目
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .meta_parser import parse_media
from .mteam import TorrentInfo  # 保留类型引用以保持兼容性
from .pt_client import PTClient
from .qbit import QBitClient
from .store import Store
from .tmdb_client import TmdbClient

logger = logging.getLogger(__name__)


class SubscriptionError(Exception):
    pass


class SubscriptionManager:
    def __init__(
        self,
        store: Store,
        tmdb: TmdbClient,
        pt_client: PTClient,  # 通用 PT 客户端接口
        qbit: QBitClient,
        libraries: dict[str, str],
        notifier: Callable[[str], None] | None = None,
    ):
        self.store = store
        self.tmdb = tmdb
        self.pt_client = pt_client  # 支持任意 PT 站点
        self.qbit = qbit
        self.libraries = libraries
        self.notifier = notifier

    # -------- 订阅 CRUD --------
    def add_subscription(self, tmdb_id: str, sub_type: str, season_filter: int | None = None) -> int:
        sub_type = sub_type.lower()
        if sub_type not in ("movie", "tv"):
            raise SubscriptionError("订阅类型必须是 movie 或 tv")

        if sub_type == "movie":
            detail = self.tmdb.movie_detail(int(tmdb_id))
            title, _ = self.tmdb.extract_titles(detail, is_movie=True)
            year = ""
            if detail.get("release_date"):
                year = str(detail["release_date"])[:4]
            sub_id = self.store.add_subscription(
                tmdb_id=str(tmdb_id),
                sub_type="movie",
                title=title,
                year=year,
                season_filter=None,
            )
            # 为电影只建一条 item（episode=None）
            self.store.upsert_items(
                sub_id,
                [
                    {
                        "season": 0,
                        "episode": 0,
                        "name": title,
                        "air_date": detail.get("release_date", ""),
                    }
                ],
            )
            return sub_id

        # tv
        detail = self.tmdb.tv_detail(int(tmdb_id))
        title, _ = self.tmdb.extract_titles(detail, is_movie=False)
        year = ""
        if detail.get("first_air_date"):
            year = str(detail["first_air_date"])[:4]
        # 若指定 season_filter，仅订阅该季
        season_filter = int(season_filter) if season_filter else None
        sub_id = self.store.add_subscription(
            tmdb_id=str(tmdb_id),
            sub_type="tv",
            title=title,
            year=year,
            season_filter=season_filter,
        )

        # 初始化 seasons/episodes
        seasons = detail.get("seasons") or []
        items: list[dict[str, Any]] = []
        for s in seasons:
            s_no = s.get("season_number")
            if s_no is None or s_no < 0:
                continue
            if season_filter and int(s_no) != int(season_filter):
                continue
            s_detail = self.tmdb.tv_season_detail(int(tmdb_id), int(s_no))
            for ep in s_detail.get("episodes") or []:
                items.append(
                    {
                        "season": s_no,
                        "episode": ep.get("episode_number"),
                        "name": ep.get("name") or "",
                        "air_date": ep.get("air_date") or "",
                    }
                )
        if items:
            self.store.upsert_items(sub_id, items)
        return sub_id

    def delete_subscription(self, sub_id: int) -> None:
        self.store.delete_subscription(sub_id)

    @staticmethod
    def _is_subscription_finished(counts: dict[str, int]) -> bool:
        total = int(counts.get("total") or 0)
        downloaded = int(counts.get("downloaded") or 0)
        return total > 0 and downloaded >= total

    def _sync_subscription_state(self, sub: dict[str, Any]) -> None:
        sf = sub.get("season_filter")
        counts = self.store.get_subscription_counts(sub["id"], season_filter=sf)
        finished = self._is_subscription_finished(counts)
        status = "finished" if finished else "active"
        if bool(sub.get("finished")) != finished or str(sub.get("status") or "active") != status:
            self.store.update_subscription_state(sub["id"], finished=finished)

        sub["finished"] = finished
        sub["status"] = status
        sub["total"] = int(counts.get("total") or 0)
        sub["downloaded"] = int(counts.get("downloaded") or 0)
        sub["organized"] = int(counts.get("organized") or 0)

    def list_subscriptions(self, limit: int = 50) -> list[dict[str, Any]]:
        subs = self.store.list_subscriptions(limit=limit)
        for s in subs:
            self._sync_subscription_state(s)
        return subs

    # -------- 本地扫描：标记已整理 --------
    def _scan_local_tv(self, sub: dict[str, Any]) -> None:
        lib_tv = self.libraries.get("tv")
        if not lib_tv:
            logger.warning(f"[scan_local_tv] TV library not configured, skipping scan for sub_id={sub.get('id')}")
            return
        root = Path(lib_tv)
        if not root.exists():
            logger.warning(f"[scan_local_tv] TV library path does not exist: {root}")
            return
        title = sub.get("title", "")
        sub_id = sub.get("id")
        logger.info(f"[scan_local_tv] Starting scan for sub_id={sub_id}, title='{title}', root={root}")
        # 优化：只扫描可能的剧集目录（包含标题的目录），避免全库遍历
        candidate_dirs: list[Path] = []
        try:
            all_dirs = list(root.iterdir())
            logger.info(f"[scan_local_tv] Found {len(all_dirs)} directories in {root}")
            for d in all_dirs:
                if d.is_dir():
                    if not title or title in d.name:
                        candidate_dirs.append(d)
                        logger.info(f"[scan_local_tv] ✓ Candidate dir: {d.name}")
                    else:
                        logger.debug(f"[scan_local_tv] ✗ Skipped dir (title not match): {d.name}")
        except Exception as e:
            logger.error(f"[scan_local_tv] Error listing directories: {e}")
            candidate_dirs = [root]

        if not candidate_dirs:
            logger.warning(f"[scan_local_tv] No candidate directories found for title='{title}'")
            candidate_dirs = [root]

        logger.info(f"[scan_local_tv] Scanning {len(candidate_dirs)} candidate directories")

        for base in candidate_dirs or [root]:
            for vf in base.rglob("*"):
                if not vf.is_file():
                    continue
                parsed = parse_media(name=vf.name, parent_path=str(vf.parent))
                if parsed.media_type != "tv" or parsed.season is None or parsed.episode is None:
                    continue
                # 粗匹配：文件名/目录名包含订阅标题
                name_join = f"{vf.parent.name} {vf.name}"
                if title and title not in name_join:
                    continue
                # 本地存在即视为“已下载”（可能不是本程序下载的），同时标记已整理
                with contextlib.suppress(Exception):
                    self.store.mark_item_downloaded(
                        sub["id"],
                        int(parsed.season),
                        int(parsed.episode),
                        torrent_hash="",
                        mteam_id="",
                    )
                self.store.mark_item_organized(sub["id"], parsed.season, parsed.episode)

    def _scan_local_movie(self, sub: dict[str, Any]) -> None:
        lib_movie = self.libraries.get("movie")
        if not lib_movie:
            return
        root = Path(lib_movie)
        if not root.exists():
            return
        title = sub.get("title", "")
        year = sub.get("year", "")
        # 优化：只扫描可能的电影目录（包含标题的目录），避免全库遍历
        candidate_dirs: list[Path] = []
        try:
            for d in root.iterdir():
                if d.is_dir() and (not title or title in d.name):
                    candidate_dirs.append(d)
        except Exception:
            candidate_dirs = [root]

        for base in candidate_dirs or [root]:
            for vf in base.rglob("*"):
                if not vf.is_file():
                    continue
                parsed = parse_media(name=vf.name, parent_path=str(vf.parent))
                if parsed.media_type != "movie":
                    continue
                if title and title not in vf.name:
                    continue
                if year and parsed.year and parsed.year != year:
                    continue
                with contextlib.suppress(Exception):
                    self.store.mark_item_downloaded(sub["id"], 0, 0, torrent_hash="", mteam_id="")
                self.store.mark_item_organized(sub["id"], 0, 0)

    def scan_local(self) -> None:
        subs = self.store.list_subscriptions(limit=200)
        for sub in subs:
            if sub["type"] == "tv":
                self._scan_local_tv(sub)
            else:
                self._scan_local_movie(sub)
            self._sync_subscription_state(sub)

    # -------- 轮询并自动下载 --------
    def poll_and_download(self, max_subs: int = 20, max_items_per_sub: int = 5):
        subs = self.store.list_subscriptions(limit=max_subs)
        for sub in subs:
            self._sync_subscription_state(sub)
            if sub.get("finished"):
                continue
            # 本地扫描，标记已整理
            if sub["type"] == "tv":
                self._scan_local_tv(sub)
            else:
                self._scan_local_movie(sub)

            if sub["type"] == "tv":
                self._process_tv(sub, max_items_per_sub)
            else:
                self._process_movie(sub)
            self._sync_subscription_state(sub)

    def _pick_best(self, results: list[TorrentInfo]) -> TorrentInfo:
        """
        从多个搜索结果中选择最佳资源
        优先级：中字 > 高分辨率 > HDR/DoVi > 做种数多
        """
        if not results:
            raise ValueError("No results to pick from")
        if len(results) == 1:
            return results[0]

        def score(t: TorrentInfo) -> tuple[int, int, int, int]:
            # 返回元组，按顺序比较优先级
            name_upper = t.name.upper()

            # 1. 字幕优先级（中字最高）
            subtitle_score = 0
            if t.tag_subtitle == "中字" or "中字" in name_upper or "CHINESE" in name_upper:
                subtitle_score = 100
            elif "简体" in t.name or "繁体" in t.name or "字幕" in t.name:
                subtitle_score = 80
            elif t.tag_subtitle == "无字":
                subtitle_score = 0

            # 2. 分辨率优先级
            resolution_score = 0
            res = t.tag_resolution.upper()
            if res in ("4K", "2160P"):
                resolution_score = 100
            elif res == "1080P":
                resolution_score = 80
            elif res == "720P":
                resolution_score = 50
            else:
                # 从文件名解析
                if "2160P" in name_upper or "4K" in name_upper:
                    resolution_score = 100
                elif "1080P" in name_upper:
                    resolution_score = 80
                elif "720P" in name_upper:
                    resolution_score = 50

            # 3. HDR/来源优先级
            hdr_score = 0
            if "REMUX" in name_upper:
                hdr_score = 50
            elif "BLURAY" in name_upper or "BLU-RAY" in name_upper:
                hdr_score = 40
            if t.tag_hdr:
                hdr_score += 20  # HDR/DoVi 加分

            # 4. 做种数（上限 100）
            seeder_score = min(t.seeders, 100)

            return (subtitle_score, resolution_score, hdr_score, seeder_score)

        best = max(results, key=score)
        logger.info(
            f"[subscription] picked best: {best.name[:50]} "
            f"(中字={best.tag_subtitle}, 分辨率={best.tag_resolution}, "
            f"做种={best.seeders}) from {len(results)} results"
        )
        return best

    def _process_tv(self, sub: dict[str, Any], max_items: int):
        pending = self.store.list_pending_items(sub["id"], limit=max_items)
        if not pending:
            return
        title = sub.get("title", "")
        tmdb_id = sub.get("tmdb_id")
        for item in pending:
            s = item.get("season")
            e = item.get("episode")
            keyword = f"{title} S{s:02d}E{e:02d}"
            try:
                # 注意：M-Team 搜索页码从 1 开始，传 0 会触发“參數錯誤”
                results = self.pt_client.search(keyword=keyword, category_key="tv", page=1)
                if not results:
                    continue
                t = self._pick_best(results)
                download_url = self.pt_client.get_download_url(t.id)
                torrent_bytes, _ = self.pt_client.download_torrent_file(download_url)
                torrent_hash = self.qbit.add_torrent(content=torrent_bytes, category="tv", save_path=None)
                self.store.mark_item_downloaded(sub["id"], s, e, torrent_hash=torrent_hash, mteam_id=t.id)
                if self.notifier:
                    self.notifier(f"📺 订阅自动下载：{title} S{s:02d}E{e:02d}\n🔎 Hash: {torrent_hash}")
            except Exception as ex:
                logger.warning(f"[subscription] tv download failed tmdb={tmdb_id} S{s}E{e} keyword={keyword!r}: {ex}")

    def _process_movie(self, sub: dict[str, Any]):
        items = self.store.list_pending_items(sub["id"], limit=1)
        if not items:
            return
        title = sub.get("title", "")
        year = sub.get("year", "")
        keyword = f"{title} {year}".strip()
        try:
            # 注意：M-Team 搜索页码从 1 开始，传 0 会触发“參數錯誤”
            results = self.pt_client.search(keyword=keyword, category_key="movie", page=1)
            if not results:
                return
            t = self._pick_best(results)
            download_url = self.pt_client.get_download_url(t.id)
            torrent_bytes, _ = self.pt_client.download_torrent_file(download_url)
            torrent_hash = self.qbit.add_torrent(content=torrent_bytes, category="movie", save_path=None)
            self.store.mark_item_downloaded(sub["id"], 0, 0, torrent_hash=torrent_hash, mteam_id=t.id)
            if self.notifier:
                self.notifier(f"🎬 订阅自动下载：{title} {year}\n🔎 Hash: {torrent_hash}")
        except Exception as ex:
            logger.warning(f"[subscription] movie download failed tmdb={sub.get('tmdb_id')} keyword={keyword!r}: {ex}")
