"""
SQLite 存储：用于整理去重、日志、待人工确认队列、下载记录
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any


def _now_ts() -> int:
    return int(time.time())


@dataclass
class OrganizeRecord:
    torrent_hash: str
    file_rel: str
    dest_rel: str
    status: str  # copied / skipped / failed
    message: str = ""
    created_ts: int = 0


@dataclass
class DownloadRecord:
    """记录通过本程序添加的下载任务"""

    torrent_hash: str
    torrent_name: str
    category: str = ""
    mteam_id: str = ""  # M-Team 种子 ID
    organized: bool = False  # 是否已整理
    created_ts: int = 0


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS organize_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    torrent_hash TEXT NOT NULL,
                    file_rel TEXT NOT NULL,
                    dest_rel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    created_ts INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_org_unique
                ON organize_records(torrent_hash, file_rel, dest_rel);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_manual (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    torrent_hash TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    created_ts INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unique ON pending_manual(torrent_hash);")

            # 任务表：用于展示整理进度与历史
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS organize_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    mode TEXT NOT NULL, -- manual/auto
                    torrent_hash TEXT NOT NULL,
                    torrent_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, -- queued/running/success/failed
                    total_items INTEGER NOT NULL DEFAULT 0,
                    done_items INTEGER NOT NULL DEFAULT 0,
                    current_item TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    created_ts INTEGER NOT NULL,
                    started_ts INTEGER,
                    finished_ts INTEGER
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unique ON organize_tasks(task_id);")

            # 兼容旧库：补列 file_size_bytes, duration_seconds
            with contextlib.suppress(Exception):
                conn.execute("ALTER TABLE organize_tasks ADD COLUMN file_size_bytes INTEGER NOT NULL DEFAULT 0;")
            with contextlib.suppress(Exception):
                conn.execute("ALTER TABLE organize_tasks ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 0;")
            # 补列 media_type, dest_path
            with contextlib.suppress(Exception):
                conn.execute("ALTER TABLE organize_tasks ADD COLUMN media_type TEXT NOT NULL DEFAULT '';")
            with contextlib.suppress(Exception):
                conn.execute("ALTER TABLE organize_tasks ADD COLUMN dest_path TEXT NOT NULL DEFAULT '';")
            # 下载记录表：记录通过本程序添加的下载任务（用于自动整理模式过滤）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS download_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    torrent_hash TEXT NOT NULL,
                    torrent_name TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    mteam_id TEXT NOT NULL DEFAULT '',
                    organized INTEGER NOT NULL DEFAULT 0,
                    created_ts INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_download_hash ON download_records(torrent_hash);")

            # 订阅表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tmdb_id TEXT NOT NULL,
                    type TEXT NOT NULL, -- movie/tv
                    title TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '',
                    season_filter INTEGER, -- 可选：仅订阅某一季（仅 tv 有意义）
                    status TEXT NOT NULL DEFAULT 'active', -- active/finished
                    finished INTEGER NOT NULL DEFAULT 0,
                    created_ts INTEGER NOT NULL,
                    updated_ts INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sub_tmdb ON subscriptions(tmdb_id, type);")

            # 兼容旧库：补列 season_filter
            with contextlib.suppress(Exception):
                conn.execute("ALTER TABLE subscriptions ADD COLUMN season_filter INTEGER;")

            # 订阅条目表（剧集或电影单条）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscription_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sub_id INTEGER NOT NULL,
                    season INTEGER,
                    episode INTEGER,
                    name TEXT NOT NULL DEFAULT '',
                    air_date TEXT NOT NULL DEFAULT '',
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    organized INTEGER NOT NULL DEFAULT 0,
                    torrent_hash TEXT NOT NULL DEFAULT '',
                    mteam_id TEXT NOT NULL DEFAULT '',
                    created_ts INTEGER NOT NULL,
                    updated_ts INTEGER NOT NULL,
                    UNIQUE(sub_id, season, episode)
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_items_sub ON subscription_items(sub_id);")

    def has_record(self, torrent_hash: str, file_rel: str, dest_rel: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM organize_records WHERE torrent_hash=? AND file_rel=? AND dest_rel=? LIMIT 1",
                (torrent_hash, file_rel, dest_rel),
            ).fetchone()
            return row is not None

    def add_record(self, rec: OrganizeRecord) -> None:
        if not rec.created_ts:
            rec.created_ts = _now_ts()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO organize_records (torrent_hash, file_rel, dest_rel, status, message, created_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.torrent_hash,
                    rec.file_rel,
                    rec.dest_rel,
                    rec.status,
                    rec.message,
                    rec.created_ts,
                ),
            )

    def add_pending(self, torrent_hash: str, name: str, reason: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO pending_manual (torrent_hash, name, reason, created_ts)
                VALUES (?, ?, ?, ?)
                """,
                (torrent_hash, name or "", reason or "", _now_ts()),
            )

    def pop_pending(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT torrent_hash, name, reason, created_ts FROM pending_manual ORDER BY created_ts ASC LIMIT ?",
                (limit,),
            ).fetchall()
            # 不删除，让人工确认后再删除（后续实现）
            return [dict(r) for r in rows]

    def clear_pending(self, torrent_hash: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM pending_manual WHERE torrent_hash=?", (torrent_hash,))

    def upsert_task(self, task: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO organize_tasks
                    (task_id, mode, torrent_hash, torrent_name, status, total_items,
                     done_items, current_item, message, file_size_bytes, duration_seconds,
                     media_type, dest_path, created_ts, started_ts, finished_ts)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    mode=excluded.mode,
                    torrent_hash=excluded.torrent_hash,
                    torrent_name=excluded.torrent_name,
                    status=excluded.status,
                    total_items=excluded.total_items,
                    done_items=excluded.done_items,
                    current_item=excluded.current_item,
                    message=excluded.message,
                    file_size_bytes=excluded.file_size_bytes,
                    duration_seconds=excluded.duration_seconds,
                    media_type=CASE
                        WHEN excluded.media_type != '' THEN excluded.media_type
                        ELSE organize_tasks.media_type
                    END,
                    dest_path=CASE
                        WHEN excluded.dest_path != '' THEN excluded.dest_path
                        ELSE organize_tasks.dest_path
                    END,
                    started_ts=excluded.started_ts,
                    finished_ts=excluded.finished_ts
                """,
                (
                    task.get("task_id"),
                    task.get("mode", "manual"),
                    task.get("torrent_hash", ""),
                    task.get("torrent_name", ""),
                    task.get("status", "queued"),
                    int(task.get("total_items", 0) or 0),
                    int(task.get("done_items", 0) or 0),
                    task.get("current_item", "") or "",
                    task.get("message", "") or "",
                    int(task.get("file_size_bytes", 0) or 0),
                    int(task.get("duration_seconds", 0) or 0),
                    task.get("media_type", "") or "",
                    task.get("dest_path", "") or "",
                    int(task.get("created_ts", _now_ts()) or _now_ts()),
                    task.get("started_ts"),
                    task.get("finished_ts"),
                ),
            )

    def list_tasks(
        self,
        limit: int = 30,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT task_id, mode, torrent_hash, torrent_name, status,
                           total_items, done_items, current_item, message,
                           file_size_bytes, duration_seconds, media_type, dest_path,
                           created_ts, started_ts, finished_ts
                    FROM organize_tasks
                    WHERE status = ?
                    ORDER BY created_ts DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT task_id, mode, torrent_hash, torrent_name, status,
                           total_items, done_items, current_item, message,
                           file_size_bytes, duration_seconds, media_type, dest_path,
                           created_ts, started_ts, finished_ts
                    FROM organize_tasks
                    ORDER BY created_ts DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return [dict(r) for r in rows]

    def count_tasks(self, status: str | None = None) -> int:
        """统计任务总数"""
        with self._conn() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) FROM organize_tasks WHERE status = ?",
                    (status,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM organize_tasks").fetchone()
            return row[0] if row else 0

    # ============ 下载记录相关 ============

    def add_download(self, rec: DownloadRecord) -> None:
        """记录通过本程序添加的下载任务"""
        if not rec.created_ts:
            rec.created_ts = _now_ts()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO download_records
                    (torrent_hash, torrent_name, category, mteam_id, organized, created_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.torrent_hash,
                    rec.torrent_name,
                    rec.category,
                    rec.mteam_id,
                    int(rec.organized),
                    rec.created_ts,
                ),
            )

    def has_download(self, torrent_hash: str) -> bool:
        """检查是否是通过本程序添加的下载"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM download_records WHERE torrent_hash=? LIMIT 1",
                (torrent_hash,),
            ).fetchone()
            return row is not None

    def is_download_organized(self, torrent_hash: str) -> bool:
        """检查下载是否已整理"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT organized FROM download_records WHERE torrent_hash=? LIMIT 1",
                (torrent_hash,),
            ).fetchone()
            return bool(row and row[0])

    def mark_download_organized(self, torrent_hash: str) -> None:
        """标记下载已整理"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE download_records SET organized=1 WHERE torrent_hash=?",
                (torrent_hash,),
            )

    def list_unorganized_downloads(self, limit: int = 50) -> list[dict[str, Any]]:
        """列出未整理的下载（用于自动整理模式）"""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT torrent_hash, torrent_name, category, mteam_id, organized, created_ts
                FROM download_records
                WHERE organized=0
                ORDER BY created_ts ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ============ 订阅相关 ============

    def add_subscription(
        self,
        tmdb_id: str,
        sub_type: str,
        title: str,
        year: str = "",
        finished: bool = False,
        season_filter: int | None = None,
    ) -> int:
        now = _now_ts()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO subscriptions
                    (id, tmdb_id, type, title, year, season_filter, status,
                     finished, created_ts, updated_ts)
                VALUES (
                    COALESCE((SELECT id FROM subscriptions WHERE tmdb_id=? AND type=?), NULL),
                    ?, ?, ?, ?, ?, ?, ?,
                    COALESCE((SELECT created_ts FROM subscriptions WHERE tmdb_id=? AND type=?), ?),
                    ?
                )
                """,
                (
                    tmdb_id,
                    sub_type,
                    tmdb_id,
                    sub_type,
                    title,
                    year or "",
                    season_filter,
                    "active",
                    1 if finished else 0,
                    tmdb_id,
                    sub_type,
                    now,
                    now,
                ),
            )
            sub_id = cur.lastrowid
            # 如果 replace 但 lastrowid 可能为 0，取现有 id
            if not sub_id:
                row = conn.execute(
                    "SELECT id FROM subscriptions WHERE tmdb_id=? AND type=?",
                    (tmdb_id, sub_type),
                ).fetchone()
                sub_id = row[0] if row else 0
            return sub_id

    def delete_subscription(self, sub_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM subscription_items WHERE sub_id=?", (sub_id,))
            conn.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))

    def list_subscriptions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, tmdb_id, type, title, year, season_filter, status, finished, created_ts, updated_ts
                FROM subscriptions
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_subscription(self, sub_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, tmdb_id, type, title, year, season_filter,
                       status, finished, created_ts, updated_ts
                FROM subscriptions WHERE id=?
                """,
                (sub_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_subscription_state(self, sub_id: int, finished: bool) -> None:
        """更新订阅状态（active/finished）"""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET status=?, finished=?, updated_ts=?
                WHERE id=?
                """,
                (
                    "finished" if finished else "active",
                    1 if finished else 0,
                    _now_ts(),
                    sub_id,
                ),
            )

    def upsert_items(self, sub_id: int, items: list[dict[str, Any]]) -> None:
        now = _now_ts()
        with self._conn() as conn:
            for it in items:
                conn.execute(
                    """
                    INSERT INTO subscription_items
                        (sub_id, season, episode, name, air_date, downloaded,
                         organized, torrent_hash, mteam_id, created_ts, updated_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sub_id, season, episode) DO UPDATE SET
                        name=excluded.name,
                        air_date=excluded.air_date,
                        updated_ts=excluded.updated_ts
                    """,
                    (
                        sub_id,
                        it.get("season"),
                        it.get("episode"),
                        it.get("name", ""),
                        it.get("air_date", ""),
                        int(it.get("downloaded", 0)),
                        int(it.get("organized", 0)),
                        it.get("torrent_hash", "") or "",
                        it.get("mteam_id", "") or "",
                        now,
                        now,
                    ),
                )

    def mark_item_downloaded(
        self,
        sub_id: int,
        season: int,
        episode: int,
        torrent_hash: str = "",
        mteam_id: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE subscription_items
                SET downloaded=1, torrent_hash=?, mteam_id=?, updated_ts=?
                WHERE sub_id=? AND season=? AND episode=?
                """,
                (
                    torrent_hash or "",
                    mteam_id or "",
                    _now_ts(),
                    sub_id,
                    season,
                    episode,
                ),
            )

    def mark_item_organized(self, sub_id: int, season: int, episode: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE subscription_items
                SET organized=1, updated_ts=?
                WHERE sub_id=? AND season=? AND episode=?
                """,
                (_now_ts(), sub_id, season, episode),
            )

    def list_items(self, sub_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT season, episode, name, air_date, downloaded, organized, torrent_hash, mteam_id, updated_ts
                FROM subscription_items
                WHERE sub_id=?
                ORDER BY season ASC, episode ASC
                """,
                (sub_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_pending_items(self, sub_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT season, episode, name, air_date, downloaded, organized, torrent_hash, mteam_id
                FROM subscription_items
                WHERE sub_id=? AND downloaded=0
                ORDER BY season ASC, episode ASC
                LIMIT ?
                """,
                (sub_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_subscription_counts(self, sub_id: int, season_filter: int | None = None) -> dict[str, int]:
        """
        快速统计订阅进度（避免全量拉取 items）
        返回：{"total": x, "downloaded": y, "organized": z}
        """
        with self._conn() as conn:
            where = "WHERE sub_id=?"
            params: list[Any] = [sub_id]
            if season_filter and int(season_filter) > 0:
                where += " AND season=?"
                params.append(int(season_filter))
            row = conn.execute(
                f"""
                SELECT
                    COUNT(1) AS total,
                    SUM(CASE WHEN downloaded=1 THEN 1 ELSE 0 END) AS downloaded,
                    SUM(CASE WHEN organized=1 THEN 1 ELSE 0 END) AS organized
                FROM subscription_items
                {where}
                """,
                tuple(params),
            ).fetchone()
            if not row:
                return {"total": 0, "downloaded": 0, "organized": 0}
            return {
                "total": int(row["total"] or 0),
                "downloaded": int(row["downloaded"] or 0),
                "organized": int(row["organized"] or 0),
            }
