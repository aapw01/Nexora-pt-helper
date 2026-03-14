"""
订阅管理 API
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from api.state import app_state

router = APIRouter()


class AddSubscriptionRequest(BaseModel):
    """添加订阅请求"""

    tmdb_id: str
    sub_type: str  # "tv" | "movie"
    season_filter: int | None = None


def _calc_subscription_status(counts: dict) -> tuple[str, bool]:
    total = int(counts.get("total") or 0)
    downloaded = int(counts.get("downloaded") or 0)
    finished = total > 0 and downloaded >= total
    return ("finished" if finished else "active"), finished


@router.get("/subscriptions/config")
async def get_subscription_config():
    """获取订阅配置"""
    from modules.config import get_config

    config = get_config()
    sub_cfg = config.subscription

    return {
        "enabled": sub_cfg.get("enabled", False),
        "interval_minutes": sub_cfg.get("interval_minutes", 30),
        "max_subscriptions": sub_cfg.get("max_subscriptions", 20),
    }


@router.get("/subscriptions")
async def get_subscriptions(limit: int = 50):
    """获取订阅列表"""
    if not app_state.store:
        raise HTTPException(status_code=503, detail="Store 未初始化")

    try:
        if app_state.subscription_manager:
            subs = app_state.subscription_manager.list_subscriptions(limit=limit)
        else:
            subs = app_state.store.list_subscriptions(limit=limit)
        result = []
        for sub in subs:
            # 获取订阅进度统计
            counts = {
                "total": int(sub.get("total", 0)),
                "downloaded": int(sub.get("downloaded", 0)),
                "organized": int(sub.get("organized", 0)),
            }
            if counts["total"] == 0 and counts["downloaded"] == 0 and counts["organized"] == 0:
                counts = app_state.store.get_subscription_counts(sub["id"], sub.get("season_filter"))
            status, finished = _calc_subscription_status(counts)
            result.append(
                {
                    "id": sub["id"],
                    "tmdb_id": sub["tmdb_id"],
                    "type": sub["type"],
                    "title": sub["title"],
                    "year": sub.get("year", ""),
                    "season_filter": sub.get("season_filter"),
                    "status": status,
                    "status_text": "已完成" if finished else "更新中",
                    "finished": finished,
                    "created_at": sub.get("created_ts", 0),
                    "progress": counts,
                }
            )
        return {"subscriptions": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取订阅列表失败: {e!s}")


@router.get("/subscriptions/{sub_id}")
async def get_subscription(sub_id: int):
    """获取订阅详情（含各集状态）"""
    if not app_state.store:
        raise HTTPException(status_code=503, detail="Store 未初始化")

    try:
        sub = app_state.store.get_subscription(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="订阅不存在")

        # 获取各集状态
        items = app_state.store.list_items(sub_id)
        counts = app_state.store.get_subscription_counts(sub_id, sub.get("season_filter"))
        status, finished = _calc_subscription_status(counts)
        if bool(sub.get("finished", False)) != finished or str(sub.get("status") or "active") != status:
            app_state.store.update_subscription_state(sub_id, finished=finished)

        return {
            "id": sub["id"],
            "tmdb_id": sub["tmdb_id"],
            "type": sub["type"],
            "title": sub["title"],
            "year": sub.get("year", ""),
            "season_filter": sub.get("season_filter"),
            "status": status,
            "status_text": "已完成" if finished else "更新中",
            "finished": finished,
            "progress": counts,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取订阅详情失败: {e!s}")


@router.post("/subscriptions")
async def add_subscription(request: AddSubscriptionRequest):
    """添加订阅"""
    if not app_state.subscription_manager:
        raise HTTPException(status_code=503, detail="订阅管理器未初始化")

    try:
        sub_id = app_state.subscription_manager.add_subscription(
            tmdb_id=request.tmdb_id,
            sub_type=request.sub_type,
            season_filter=request.season_filter,
        )
        return {"success": True, "id": sub_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加订阅失败: {e!s}")


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int):
    """删除订阅"""
    if not app_state.subscription_manager:
        raise HTTPException(status_code=503, detail="订阅管理器未初始化")

    try:
        app_state.subscription_manager.delete_subscription(sub_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除订阅失败: {e!s}")


@router.get("/tmdb/details")
async def get_tmdb_details(
    tmdb_id: int = Query(..., description="TMDB ID"),
    type: str = Query("tv", description="类型 (tv/movie)"),
):
    """获取 TMDB 详情"""
    if not app_state.tmdb:
        raise HTTPException(status_code=503, detail="TMDB 客户端未初始化")

    try:
        if type == "tv":
            detail = app_state.tmdb.tv_detail(tmdb_id)
            return {"number_of_seasons": detail.get("number_of_seasons", 0)}
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {e!s}")


@router.get("/tmdb/search")
async def search_tmdb(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    type: str = Query("tv", description="类型 (tv/movie)"),
):
    """搜索 TMDB（支持关键词标准化和季号提取）"""
    if not app_state.tmdb:
        raise HTTPException(status_code=503, detail="TMDB 客户端未初始化")

    try:
        # 导入标准化函数
        from modules.tmdb_client import normalize_search_query

        # 标准化关键词并提取季号
        normalized = normalize_search_query(q)
        clean_query = normalized["query"]
        season = normalized["season"]

        # 根据类型搜索
        results = app_state.tmdb.search_tv(clean_query) if type == "tv" else app_state.tmdb.search_movie(clean_query)

        return {
            "results": [
                {
                    "id": r.get("id"),
                    "title": r.get("name") or r.get("title"),
                    "original_title": r.get("original_name") or r.get("original_title"),
                    "overview": r.get("overview", ""),
                    "poster_path": r.get("poster_path"),
                    "first_air_date": r.get("first_air_date") or r.get("release_date"),
                    "vote_average": r.get("vote_average", 0),
                    "number_of_seasons": (r.get("number_of_seasons") if type == "tv" else None),
                }
                for r in results
            ],
            "season": season,  # 返回提取的季号
            "original_query": q,
            "normalized_query": clean_query,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TMDB 搜索失败: {e!s}")


@router.post("/subscriptions/{sub_id}/refresh")
async def refresh_subscription(sub_id: int):
    """刷新单个订阅的本地文件状态"""
    if not app_state.subscription_manager:
        raise HTTPException(status_code=503, detail="订阅管理器未初始化")

    try:
        # 获取订阅信息
        sub = app_state.store.get_subscription(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="订阅不存在")

        # 执行本地扫描
        if sub.get("type") == "tv":
            app_state.subscription_manager._scan_local_tv(sub)
        else:
            app_state.subscription_manager._scan_local_movie(sub)

        # 重新获取统计数据
        counts = app_state.store.get_subscription_counts(sub_id, sub.get("season_filter"))
        status, finished = _calc_subscription_status(counts)
        app_state.store.update_subscription_state(sub_id, finished=finished)

        return {
            "success": True,
            "message": "刷新完成",
            "status": status,
            "status_text": "已完成" if finished else "更新中",
            "progress": counts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刷新失败: {e!s}")


@router.post("/subscriptions/refresh-all")
async def refresh_all_subscriptions(background_tasks: BackgroundTasks):
    """异步刷新所有订阅的本地文件状态"""
    if not app_state.subscription_manager:
        raise HTTPException(status_code=503, detail="订阅管理器未初始化")

    def _refresh_all():
        """后台任务：刷新所有订阅"""
        try:
            subs = app_state.subscription_manager.list_subscriptions(limit=200)
            for sub in subs:
                if sub.get("finished"):
                    continue
                if sub.get("type") == "tv":
                    app_state.subscription_manager._scan_local_tv(sub)
                else:
                    app_state.subscription_manager._scan_local_movie(sub)
                counts = app_state.store.get_subscription_counts(sub["id"], sub.get("season_filter"))
                _, finished = _calc_subscription_status(counts)
                app_state.store.update_subscription_state(sub["id"], finished=finished)
        except Exception as e:
            import logging

            logging.getLogger(__name__).error(f"全部刷新失败: {e}")

    # 添加到后台任务
    background_tasks.add_task(_refresh_all)

    return {"success": True, "message": "已启动后台刷新任务"}
