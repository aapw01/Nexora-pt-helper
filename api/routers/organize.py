"""
资源整理 API
"""

from fastapi import APIRouter, HTTPException

from api.state import app_state

router = APIRouter()


@router.get("/organize/tasks")
async def get_organize_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
):
    """
    获取整理任务列表（分页）

    - page: 页码（从 1 开始）
    - page_size: 每页数量（默认 20，最大 100）
    - status: 可选过滤状态（success/failed/running/queued）
    """
    if not app_state.store:
        raise HTTPException(status_code=503, detail="Store 未初始化")

    try:
        # 限制 page_size 范围
        page_size = min(max(1, page_size), 100)
        page = max(1, page)
        offset = (page - 1) * page_size

        # 获取总数和分页数据
        total = app_state.store.count_tasks(status=status)
        tasks = app_state.store.list_tasks(
            limit=page_size,
            offset=offset,
            status=status,
        )

        return {
            "tasks": tasks,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {e!s}")


@router.get("/organize/records")
async def get_organize_records(limit: int = 50):
    """获取整理记录（待人工确认队列）"""
    if not app_state.store:
        raise HTTPException(status_code=503, detail="Store 未初始化")

    try:
        pending = app_state.store.pop_pending(limit=limit)
        return {"records": pending}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取记录失败: {e!s}")


@router.post("/organize/scan")
async def trigger_organize_scan():
    """手动触发整理扫描"""
    if not app_state.qbit:
        raise HTTPException(status_code=503, detail="qBittorrent 客户端未初始化")

    try:
        # 获取已完成的任务
        completed = app_state.qbit.get_torrents_by_status(status_filter="completed", limit=20)

        return {
            "success": True,
            "message": f"扫描到 {len(completed)} 个已完成任务",
            "count": len(completed),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"扫描失败: {e!s}")


@router.get("/organize/unorganized")
async def get_unorganized_downloads(limit: int = 50):
    """获取未整理的下载列表"""
    if not app_state.store:
        raise HTTPException(status_code=503, detail="Store 未初始化")

    try:
        downloads = app_state.store.list_unorganized_downloads(limit=limit)
        return {"downloads": downloads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取列表失败: {e!s}")
