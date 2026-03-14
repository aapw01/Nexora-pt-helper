"""
下载管理 API
"""

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.state import app_state

router = APIRouter()


class AddDownloadRequest(BaseModel):
    """添加下载请求"""

    torrent_id: str
    save_path: str | None = None
    category: str | None = None


class AddManualDownloadRequest(BaseModel):
    """手动添加下载请求（磁力/URL）"""

    url: str
    save_path: str | None = None
    category: str | None = None


def _is_supported_manual_url(url: str) -> bool:
    """仅允许磁力链接或 http/https URL"""
    text = (url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    return parsed.scheme in ("http", "https") or (parsed.scheme == "magnet" and text.lower().startswith("magnet:?"))


@router.get("/downloads")
async def get_downloads(
    status_filter: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
):
    """获取下载任务列表（支持分页和搜索）"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        # 计算偏移量
        offset = (page - 1) * page_size

        # 使用新的分页接口
        torrents, total = app_state.qbit.get_torrents_paged(
            category=category,
            limit=page_size,
            offset=offset,
            filter_text=q,
            status_filter=status_filter,
        )

        # 转换为统一格式
        return {
            "downloads": [
                {
                    "hash": t.hash if hasattr(t, "hash") else t.get("hash", ""),
                    "name": t.name if hasattr(t, "name") else t.get("name", ""),
                    "progress": (
                        round(t.progress * 100, 1) if hasattr(t, "progress") else round(t.get("progress", 0) * 100, 1)
                    ),
                    "state_code": (t.state_code if hasattr(t, "state_code") else t.get("state", "unknown")),
                    "state_text": (
                        t.state_text
                        if hasattr(t, "state_text")
                        else (t.state_display if hasattr(t, "state_display") else t.get("state", "unknown"))
                    ),
                    "state": (
                        t.state_display
                        if hasattr(t, "state_display")
                        else (t.state_text if hasattr(t, "state_text") else t.get("state", "unknown"))
                    ),
                    "size": t.size if hasattr(t, "size") else t.get("size", 0),
                    "downloaded": (t.downloaded if hasattr(t, "downloaded") else t.get("downloaded", 0)),
                    "uploaded": (t.uploaded if hasattr(t, "uploaded") else t.get("uploaded", 0)),
                    "dlspeed": (t.dlspeed if hasattr(t, "dlspeed") else t.get("dlspeed", 0)),
                    "upspeed": (t.upspeed if hasattr(t, "upspeed") else t.get("upspeed", 0)),
                    "eta": t.eta if hasattr(t, "eta") else t.get("eta", 0),
                    "category": (t.category if hasattr(t, "category") else t.get("category", "")),
                    "save_path": (t.save_path if hasattr(t, "save_path") else t.get("save_path", "")),
                }
                for t in torrents
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取下载列表失败: {e!s}")


@router.get("/downloads/{torrent_hash}")
async def get_download(torrent_hash: str):
    """获取单个下载任务详情"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        torrent = app_state.qbit.get_torrent(torrent_hash)
        if not torrent:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "hash": torrent.hash,
            "name": torrent.name,
            "progress": round(torrent.progress * 100, 1),
            "state_code": torrent.state_code,
            "state_text": torrent.state_text,
            "state": torrent.state_display,
            "size": torrent.size,
            "downloaded": torrent.downloaded,
            "uploaded": torrent.uploaded,
            "dlspeed": torrent.dlspeed,
            "upspeed": torrent.upspeed,
            "eta": torrent.eta,
            "category": torrent.category,
            "save_path": torrent.save_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务详情失败: {e!s}")


@router.post("/downloads")
async def add_download(request: AddDownloadRequest):
    """添加下载任务"""
    import logging

    logger = logging.getLogger(__name__)

    if not app_state.mteam:
        raise HTTPException(status_code=503, detail="M-Team 客户端未初始化")
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    logger.info(f"[API] 添加下载: torrent_id={request.torrent_id}, category={request.category}")

    try:
        # 1. 获取下载链接
        logger.info("[API] 获取下载链接...")
        download_url = app_state.mteam.get_download_url(request.torrent_id)
        logger.info("[API] 下载链接获取成功")

        # 2. 下载 torrent 文件
        logger.info("[API] 下载 torrent 文件...")
        torrent_content, filename = app_state.mteam.download_torrent_file(download_url)
        logger.info(f"[API] torrent 文件下载成功: {filename}, 大小: {len(torrent_content)} bytes")

        # 3. 添加到 qBittorrent
        logger.info("[API] 添加到 qBittorrent...")
        torrent_hash = app_state.qbit.add_torrent(
            content=torrent_content,
            save_path=request.save_path,
            category=request.category,
        )
        logger.info(f"[API] 添加成功: hash={torrent_hash}")

        # 4. 记录到数据库
        if app_state.store:
            from modules.store import DownloadRecord

            app_state.store.add_download(
                DownloadRecord(
                    torrent_hash=torrent_hash,
                    torrent_name=filename,
                    category=request.category or "",
                    mteam_id=request.torrent_id,
                )
            )
            logger.info("[API] 已记录到数据库")

        return {
            "success": True,
            "hash": torrent_hash,
            "filename": filename,
            "message": f"下载任务添加成功: {filename}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 添加下载失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"添加下载失败: {e!s}")


@router.post("/downloads/manual")
async def add_manual_download(request: AddManualDownloadRequest):
    """手动添加下载任务（magnet/http/https）"""
    import logging

    logger = logging.getLogger(__name__)

    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    url = (request.url or "").strip()
    if not _is_supported_manual_url(url):
        raise HTTPException(status_code=400, detail="仅支持 magnet 或 http/https 下载链接")

    logger.info(f"[API] 手动添加下载: category={request.category}, url={url[:120]}")

    try:
        torrent_hash = app_state.qbit.add_torrent(
            content=url,
            save_path=request.save_path,
            category=request.category,
        )
        logger.info(f"[API] 手动添加成功: hash={torrent_hash}")

        if app_state.store:
            from modules.store import DownloadRecord

            app_state.store.add_download(
                DownloadRecord(
                    torrent_hash=torrent_hash,
                    torrent_name=url,
                    category=request.category or "",
                    mteam_id="",
                )
            )
            logger.info("[API] 手动任务已记录到数据库")

        return {
            "success": True,
            "hash": torrent_hash,
            "message": "手动下载任务添加成功",
            "category": request.category or "",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 手动添加下载失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"手动添加下载失败: {e!s}")


@router.post("/downloads/{torrent_hash}/pause")
async def pause_download(torrent_hash: str):
    """暂停下载任务"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        ok = app_state.qbit.pause_torrent(torrent_hash)
        if not ok:
            raise HTTPException(status_code=500, detail="暂停失败: qBittorrent 未返回成功")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"暂停失败: {e!s}")


@router.post("/downloads/{torrent_hash}/resume")
async def resume_download(torrent_hash: str):
    """恢复下载任务"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        ok = app_state.qbit.resume_torrent(torrent_hash)
        if not ok:
            raise HTTPException(status_code=500, detail="恢复失败: qBittorrent 未返回成功")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复失败: {e!s}")


@router.delete("/downloads/{torrent_hash}")
async def delete_download(torrent_hash: str, delete_files: bool = False):
    """删除下载任务"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        ok = app_state.qbit.delete_torrent(torrent_hash, delete_files=delete_files)
        if not ok:
            raise HTTPException(status_code=500, detail="删除失败: qBittorrent 未返回成功")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e!s}")


@router.get("/qbit/categories")
async def get_qbit_categories():
    """获取 qBittorrent 分类列表"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        categories = app_state.qbit.get_categories()
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类失败: {e!s}")


class OrganizeRequest(BaseModel):
    """整理请求"""

    hashes: list[str]


@router.post("/downloads/organize")
async def organize_downloads(request: OrganizeRequest):
    """批量整理下载任务（与 TG Bot 整理逻辑一致）"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")
    if not app_state.organizer:
        raise HTTPException(status_code=503, detail="整理功能未启用")
    if not app_state.organize_queue:
        raise HTTPException(status_code=503, detail="整理队列未初始化")

    if not request.hashes:
        raise HTTPException(status_code=400, detail="请选择要整理的任务")

    task_ids = []
    errors = []

    for torrent_hash in request.hashes:
        try:
            # 获取种子信息（与 TG Bot 一致）
            tinfo = app_state.qbit.get_torrent_info(torrent_hash) or {}
            torrent_name = tinfo.get("name") or torrent_hash

            # 检查是否已下载完成
            progress = float(tinfo.get("progress", 0) or 0)
            if progress < 1.0:  # progress 是 0-1 的浮点数
                errors.append(
                    {
                        "hash": torrent_hash,
                        "name": torrent_name,
                        "error": f"任务未完成（进度: {progress * 100:.1f}%），无法整理",
                    }
                )
                continue

            files = app_state.qbit.get_torrent_files(torrent_hash)
            base_path = tinfo.get("save_path") or tinfo.get("content_path") or ""
            file_size_bytes = int(tinfo.get("size") or tinfo.get("total_size") or 0)

            if not base_path:
                errors.append({"hash": torrent_hash, "error": "无法获取下载路径"})
                continue

            # 构建整理上下文（与 TG Bot 一致）
            def make_runner(th, bp, fs, tc):
                def _runner():
                    return app_state.organizer.copy_to_library(
                        torrent_hash=th,
                        base_path=bp,
                        files=fs,
                        torrent_info=tc,
                    )

                return _runner

            torrent_ctx = {
                "name": torrent_name,
                "small_descr": "",
                "labels_new": [],
                "imdb_url": "",
            }

            # 提交到整理队列
            task_id = app_state.organize_queue.submit(
                mode="manual",
                torrent_hash=torrent_hash,
                torrent_name=torrent_name,
                runner=make_runner(torrent_hash, base_path, files, torrent_ctx),
                file_size_bytes=file_size_bytes,
            )
            task_ids.append({"hash": torrent_hash, "task_id": task_id, "name": torrent_name})

        except Exception as e:
            errors.append({"hash": torrent_hash, "error": str(e)})

    return {
        "success": len(task_ids) > 0,
        "message": f"已提交 {len(task_ids)} 个整理任务" + (f"，{len(errors)} 个失败" if errors else ""),
        "tasks": task_ids,
        "errors": errors,
    }


@router.post("/downloads/{torrent_hash}/organize")
async def organize_download(torrent_hash: str):
    """整理单个下载任务"""
    request = OrganizeRequest(hashes=[torrent_hash])
    return await organize_downloads(request)
