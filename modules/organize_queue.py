"""
单线程整理队列：一次只处理一个文件（受带宽/磁盘限制时更稳），并记录任务进度到 SQLite。
支持完成回调通知。
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .store import Store


@dataclass
class OrganizeResult:
    """整理结果"""

    ok: int = 0
    skipped: int = 0
    bad: int = 0
    total: int = 0
    dest_dir: str = ""
    media_type: str = ""
    error: str = ""


@dataclass
class QueueTask:
    task_id: str
    mode: str  # manual/auto
    torrent_hash: str
    torrent_name: str
    file_size_bytes: int  # 种子文件总大小
    runner: Callable[[], tuple[int, int, int, int, str, str]]  # returns (ok, skipped, bad, total, dest_dir, media_type)
    on_complete: Callable[[str, str, str, OrganizeResult], None] | None = None  # (task_id, mode, torrent_name, result)


class OrganizeQueue:
    def __init__(self, store: Store):
        self.store = store
        self.q: queue.Queue[QueueTask] = queue.Queue()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    @staticmethod
    def new_task_id() -> str:
        return uuid.uuid4().hex[:12]

    def submit(
        self,
        mode: str,
        torrent_hash: str,
        torrent_name: str,
        runner: Callable[[], tuple[int, int, int, int, str, str]],
        on_complete: Callable[[str, str, str, OrganizeResult], None] | None = None,
        file_size_bytes: int = 0,
    ) -> str:
        task_id = self.new_task_id()
        now = int(time.time())
        self.store.upsert_task(
            {
                "task_id": task_id,
                "mode": mode,
                "torrent_hash": torrent_hash,
                "torrent_name": torrent_name or "",
                "status": "queued",
                "total_items": 0,
                "done_items": 0,
                "current_item": "",
                "message": "",
                "file_size_bytes": file_size_bytes,
                "duration_seconds": 0,
                "media_type": "",
                "dest_path": "",
                "created_ts": now,
                "started_ts": None,
                "finished_ts": None,
            }
        )
        self.q.put(
            QueueTask(
                task_id=task_id,
                mode=mode,
                torrent_hash=torrent_hash,
                torrent_name=torrent_name or "",
                file_size_bytes=file_size_bytes,
                runner=runner,
                on_complete=on_complete,
            )
        )
        return task_id

    def _loop(self):
        while True:
            task = self.q.get()
            start_ts = int(time.time())
            self.store.upsert_task(
                {
                    "task_id": task.task_id,
                    "mode": task.mode,
                    "torrent_hash": task.torrent_hash,
                    "torrent_name": task.torrent_name,
                    "status": "running",
                    "file_size_bytes": task.file_size_bytes,
                    "started_ts": start_ts,
                }
            )
            result = OrganizeResult()
            try:
                runner_result = task.runner()
                # 兼容旧的6元素返回值和新的7元素返回值
                if len(runner_result) >= 7:
                    ok, skipped, bad, total, dest_dir, media_type, error_details = runner_result[:7]
                else:
                    ok, skipped, bad, total, dest_dir, media_type = runner_result[:6]
                    error_details = ""
                result = OrganizeResult(
                    ok=ok,
                    skipped=skipped,
                    bad=bad,
                    total=total,
                    dest_dir=dest_dir,
                    media_type=media_type,
                )
                status = "success" if bad == 0 else "failed"
                msg = f"ok={ok}, skipped={skipped}, bad={bad}, total={total}"
                if dest_dir:
                    msg += f", dest={dest_dir}"
                # 添加错误详情
                if error_details:
                    msg += f" | 错误: {error_details}"

                finished_ts = int(time.time())
                duration = finished_ts - start_ts

                self.store.upsert_task(
                    {
                        "task_id": task.task_id,
                        "mode": task.mode,
                        "torrent_hash": task.torrent_hash,
                        "torrent_name": task.torrent_name,
                        "status": status,
                        "message": msg,
                        "file_size_bytes": task.file_size_bytes,
                        "duration_seconds": duration,
                        "media_type": media_type,
                        "dest_path": dest_dir,
                        "finished_ts": finished_ts,
                    }
                )
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(
                    f"[OrganizeQueue] 任务执行异常: task_id={task.task_id} torrent={task.torrent_name} error={e}",
                    exc_info=True,
                )
                result = OrganizeResult(error=str(e))
                finished_ts = int(time.time())
                duration = finished_ts - start_ts

                self.store.upsert_task(
                    {
                        "task_id": task.task_id,
                        "mode": task.mode,
                        "torrent_hash": task.torrent_hash,
                        "torrent_name": task.torrent_name,
                        "status": "failed",
                        "message": str(e),
                        "file_size_bytes": task.file_size_bytes,
                        "duration_seconds": duration,
                        "finished_ts": finished_ts,
                    }
                )
            finally:
                # 完成回调（发送通知）
                if task.on_complete:
                    try:
                        task.on_complete(task.task_id, task.mode, task.torrent_name, result)
                    except Exception as e:
                        import logging

                        logging.getLogger(__name__).error(f"[OrganizeQueue] on_complete callback error: {e}")
                self.q.task_done()
