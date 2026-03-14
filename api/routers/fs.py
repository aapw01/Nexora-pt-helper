"""
文件系统 API - 文件浏览与本地整理
"""

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.state import app_state

router = APIRouter()
logger = logging.getLogger(__name__)


def get_allowed_roots() -> list[Path]:
    """
    获取允许浏览/操作的根目录列表
    默认包含 organize.download_root 和 organize.libraries.*
    """
    roots: list[Path] = []

    if app_state.config:
        org_cfg = app_state.config.organize or {}
        fm_cfg = app_state.config.file_manager or {}

        # 1. organize.download_root
        download_root = org_cfg.get("download_root")
        if download_root:
            roots.append(Path(download_root).resolve())

        # 2. organize.libraries.*
        libraries = org_cfg.get("libraries") or {}
        for lib_path in libraries.values():
            if lib_path:
                roots.append(Path(lib_path).resolve())

        # 3. file_manager.allowed_roots（额外配置）
        extra_roots = fm_cfg.get("allowed_roots") or []
        for r in extra_roots:
            if r:
                roots.append(Path(r).resolve())

    # 去重
    seen = set()
    unique_roots = []
    for r in roots:
        if str(r) not in seen:
            seen.add(str(r))
            unique_roots.append(r)

    return unique_roots


def is_path_allowed(path: Path, allowed_roots: list[Path]) -> bool:
    """检查路径是否在允许范围内"""
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def get_file_info(path: Path, media_exts: set[str] | None = None) -> dict:
    """获取文件/目录信息"""
    try:
        stat = path.stat()
        is_dir = path.is_dir()
        is_video = not is_dir and media_exts and path.suffix.lower() in media_exts

        return {
            "name": path.name,
            "path": str(path),
            "is_dir": is_dir,
            "is_video": is_video,
            "size": stat.st_size if not is_dir else 0,
            "mtime": stat.st_mtime,
            "ext": path.suffix.lower() if not is_dir else "",
        }
    except Exception as e:
        return {
            "name": path.name,
            "path": str(path),
            "is_dir": False,
            "is_video": False,
            "size": 0,
            "mtime": 0,
            "ext": "",
            "error": str(e),
        }


@router.get("/fs/roots")
async def get_fs_roots():
    """获取允许浏览的根目录列表"""
    roots = get_allowed_roots()
    return {"roots": [{"path": str(r), "name": r.name, "exists": r.exists()} for r in roots]}


@router.get("/fs/libraries")
async def get_libraries():
    """获取媒体库目录配置"""
    libraries = {}
    if app_state.config:
        org_cfg = app_state.config.organize or {}
        libraries = org_cfg.get("libraries") or {}
    return {"libraries": libraries}


@router.get("/fs/list")
async def list_directory(path: str = ""):
    """
    列出目录内容
    - 如果 path 为空，返回允许的根目录列表
    - 否则列出指定目录的内容
    """
    allowed_roots = get_allowed_roots()

    if not allowed_roots:
        raise HTTPException(status_code=503, detail="未配置允许浏览的目录")

    # 获取媒体文件扩展名
    media_exts: set[str] = set()
    if app_state.config:
        filters = (app_state.config.organize or {}).get("filters") or {}
        media_exts = {e.lower() for e in (filters.get("media_exts") or [])}

    if not path:
        # 返回根目录列表
        return {
            "path": "",
            "parent": None,
            "items": [
                {
                    "name": r.name,
                    "path": str(r),
                    "is_dir": True,
                    "is_video": False,
                    "size": 0,
                    "mtime": r.stat().st_mtime if r.exists() else 0,
                    "ext": "",
                }
                for r in allowed_roots
                if r.exists()
            ],
        }

    # 解析路径
    target = Path(path).resolve()

    # 安全检查
    if not is_path_allowed(target, allowed_roots):
        raise HTTPException(status_code=403, detail="路径不在允许范围内")

    if not target.exists():
        raise HTTPException(status_code=404, detail="路径不存在")

    if not target.is_dir():
        raise HTTPException(status_code=400, detail="路径不是目录")

    # 列出内容
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            # 跳过隐藏文件
            if entry.name.startswith("."):
                continue
            items.append(get_file_info(entry, media_exts))
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")

    # 计算父目录
    parent = None
    for root in allowed_roots:
        try:
            target.relative_to(root)
            if target != root:
                parent = str(target.parent)
            break
        except ValueError:
            continue

    return {
        "path": str(target),
        "parent": parent,
        "items": items,
    }


@router.get("/fs/stat")
async def stat_path(path: str):
    """获取文件/目录详情"""
    allowed_roots = get_allowed_roots()

    target = Path(path).resolve()

    if not is_path_allowed(target, allowed_roots):
        raise HTTPException(status_code=403, detail="路径不在允许范围内")

    if not target.exists():
        raise HTTPException(status_code=404, detail="路径不存在")

    media_exts: set[str] = set()
    if app_state.config:
        filters = (app_state.config.organize or {}).get("filters") or {}
        media_exts = {e.lower() for e in (filters.get("media_exts") or [])}

    info = get_file_info(target, media_exts)

    # 如果是目录，计算内部文件数量
    if target.is_dir():
        video_count = 0
        total_count = 0
        total_size = 0
        try:
            for f in target.rglob("*"):
                if f.is_file():
                    total_count += 1
                    total_size += f.stat().st_size
                    if media_exts and f.suffix.lower() in media_exts:
                        video_count += 1
        except Exception:
            pass
        info["video_count"] = video_count
        info["total_count"] = total_count
        info["total_size"] = total_size

    return info


class OrganizeRequest(BaseModel):
    """整理请求"""

    path: str | None = None  # 单路径（兼容旧版）
    paths: list[str] | None = None  # 多路径
    mode: Literal["copy", "move"] = "move"
    media_type: Literal["auto", "movie", "tv"] = "auto"
    dry_run: bool = False
    on_conflict: Literal["skip", "rename", "overwrite"] = "skip"


@router.post("/fs/organize")
async def organize_path(request: OrganizeRequest):
    """
    提交本地整理任务
    - 支持单路径 (path) 或多路径 (paths)
    - 如果 dry_run=True，只返回预览结果
    - 否则提交到整理队列异步执行
    """
    if not app_state.local_organizer:
        raise HTTPException(status_code=503, detail="本地整理器未初始化")
    if not app_state.organize_queue:
        raise HTTPException(status_code=503, detail="整理队列未初始化")

    # 收集所有路径
    all_paths: list[str] = []
    if request.paths:
        all_paths.extend(request.paths)
    elif request.path:
        all_paths.append(request.path)
    else:
        raise HTTPException(status_code=400, detail="请提供 path 或 paths 参数")

    allowed_roots = get_allowed_roots()
    targets: list[Path] = []

    for p in all_paths:
        target = Path(p).resolve()
        if not is_path_allowed(target, allowed_roots):
            raise HTTPException(status_code=403, detail=f"路径不在允许范围内: {p}")
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"路径不存在: {p}")
        targets.append(target)

    logger.info(
        f"[fs/organize] paths={len(targets)}, mode={request.mode}, "
        f"media_type={request.media_type}, dry_run={request.dry_run}"
    )

    # dry-run 模式：直接返回预览结果（合并所有路径的结果）
    if request.dry_run:
        all_files = []
        total_ok = 0
        total_skipped = 0
        total_bad = 0
        total_count = 0
        last_dest_dir = ""
        last_media_type = ""

        for target in targets:
            result = app_state.local_organizer.organize(
                source_path=target,
                mode=request.mode,
                media_type=request.media_type,
                dry_run=True,
                on_conflict=request.on_conflict,
            )
            all_files.extend(result.files)
            total_ok += result.ok
            total_skipped += result.skipped
            total_bad += result.bad
            total_count += result.total
            if result.dest_dir:
                last_dest_dir = result.dest_dir
            if result.media_type:
                last_media_type = result.media_type

        return {
            "success": True,
            "dry_run": True,
            "result": {
                "ok": total_ok,
                "skipped": total_skipped,
                "bad": total_bad,
                "total": total_count,
                "dest_dir": last_dest_dir,
                "media_type": last_media_type,
                "files": all_files,
            },
        }

    # 实际执行：为每个路径提交任务到队列
    task_ids = []
    for target in targets:
        source_name = target.name

        # 计算文件大小
        file_size_bytes = 0
        if target.is_file():
            file_size_bytes = target.stat().st_size
        else:
            try:
                for f in target.rglob("*"):
                    if f.is_file():
                        file_size_bytes += f.stat().st_size
            except Exception:
                pass

        def make_runner(t: Path):
            def _runner():
                result = app_state.local_organizer.organize(
                    source_path=t,
                    mode=request.mode,
                    media_type=request.media_type,
                    dry_run=False,
                    on_conflict=request.on_conflict,
                    source_id=f"local:{t.name}",
                )
                # 收集错误信息
                errors = []
                for f in result.files:
                    if f.get("status") == "error":
                        fname = f.get("source", "").split("/")[-1] if f.get("source") else "unknown"
                        err = f.get("error", "未知错误")
                        errors.append(f"{fname}: {err}")
                error_msg = "; ".join(errors[:5])  # 最多显示5个错误
                if len(errors) > 5:
                    error_msg += f" ...等 {len(errors)} 个错误"

                return (
                    result.ok,
                    result.skipped,
                    result.bad,
                    result.total,
                    result.dest_dir,
                    result.media_type,
                    error_msg,  # 新增：错误详情
                )

            return _runner

        task_id = app_state.organize_queue.submit(
            mode="local",
            torrent_hash="",
            torrent_name=source_name,
            runner=make_runner(target),
            file_size_bytes=file_size_bytes,
        )
        task_ids.append(task_id)

    return {
        "success": True,
        "message": f"已提交 {len(task_ids)} 个整理任务",
        "task_ids": task_ids,
    }


# Keep legacy endpoint for backwards compatibility
@router.post("/fs/preview")
async def preview_organize(request: OrganizeRequest):
    """预览整理结果（dry-run 模式的快捷方式）"""
    request.dry_run = True
    return await organize_path(request)
