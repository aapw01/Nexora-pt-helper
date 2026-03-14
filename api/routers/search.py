"""
资源搜索 API
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Query

from api.state import app_state

router = APIRouter()
logger = logging.getLogger(__name__)


def extract_imdb_id(imdb_url: str) -> str | None:
    """从 IMDb URL 提取 ID"""
    if not imdb_url:
        return None
    match = re.search(r"tt\d+", imdb_url)
    return match.group(0) if match else None


@router.get("/search/categories")
async def get_categories():
    """获取可用搜索类别"""
    if not app_state.mteam:
        raise HTTPException(status_code=503, detail="M-Team 客户端未初始化")

    return app_state.mteam.get_category_list()


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    category: str = Query("all", description="类别 (movie/tv/all)"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页数量"),
):
    """搜索 M-Team 资源（快速返回，不获取海报）"""
    if not app_state.mteam:
        raise HTTPException(status_code=503, detail="M-Team 客户端未初始化")

    try:
        results = app_state.mteam.search(
            keyword=q,
            category_key=category,
            page=page,
            page_size=page_size,
        )

        # 转换为 JSON 可序列化格式（不获取 TMDB 海报，前端异步获取）
        items = [
            {
                "id": r.id,
                "name": r.name,
                "small_descr": r.small_descr,
                "size": r.size,
                "size_bytes": r.size_bytes,
                "seeders": r.seeders,
                "leechers": r.leechers,
                "upload_date": r.upload_time,
                "category": r.category,
                "labels": getattr(r, "labels_new", r.labels or []),
                "imdb_url": r.imdb_url,
                "imdb_rating": r.imdb_rating or "",
                "douban_url": r.douban_url,
                "douban_rating": r.douban_rating or "",
                "poster": r.poster or "",  # M-Team 原生海报（如果有）
                "discount": r.discount or "",
                "tags": (
                    r.tag_list_compact.split(" · ") if hasattr(r, "tag_list_compact") and r.tag_list_compact else []
                ),
            }
            for r in results
        ]

        return {
            "results": items,
            "page": page,
            "page_size": page_size,
            "total": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {e!s}")


@router.get("/tmdb/poster")
async def get_tmdb_poster(imdb_id: str = Query(..., description="IMDb ID (如 tt0111161)")):
    """
    通过 IMDb ID 获取 TMDB 海报 URL
    返回 TMDB 图床直链，前端直接渲染
    """
    if not app_state.tmdb:
        raise HTTPException(status_code=503, detail="TMDB 客户端未初始化")

    # 确保 imdb_id 格式正确
    if not imdb_id.startswith("tt"):
        imdb_id = f"tt{imdb_id}"

    try:
        media_type, tmdb_id = app_state.tmdb.find_by_imdb(imdb_id)
        if not tmdb_id or not media_type:
            return {"poster": "", "backdrop": ""}

        # 获取详情
        detail = app_state.tmdb.movie_detail(tmdb_id) if media_type == "movie" else app_state.tmdb.tv_detail(tmdb_id)

        if not detail:
            return {"poster": "", "backdrop": ""}

        poster_path = detail.get("poster_path")
        backdrop_path = detail.get("backdrop_path")

        return {
            "poster": (app_state.tmdb.build_image_url(poster_path, original=False) if poster_path else ""),
            "backdrop": (app_state.tmdb.build_image_url(backdrop_path, original=False) if backdrop_path else ""),
            "tmdb_id": tmdb_id,
            "media_type": media_type,
        }
    except Exception as e:
        logger.debug(f"获取 TMDB 海报失败: {e}")
        return {"poster": "", "backdrop": ""}


@router.get("/tmdb/trending")
async def get_tmdb_trending(
    type: str = Query("all", description="类型 (all/movie/tv)"),
    time_window: str = Query("week", description="时间窗口 (day/week)"),
):
    """获取 TMDB 热门影视"""
    if not app_state.tmdb:
        raise HTTPException(status_code=503, detail="TMDB 客户端未初始化")

    try:
        if type == "movie":
            results = app_state.tmdb.trending_movies(time_window)
        elif type == "tv":
            results = app_state.tmdb.trending_tv(time_window)
        else:
            results = app_state.tmdb.trending_all(time_window)

        # 格式化结果
        items = []
        for r in results:
            poster = r.get("poster_path")
            backdrop = r.get("backdrop_path")
            items.append(
                {
                    "id": r.get("id"),
                    "media_type": r.get("media_type") or ("movie" if r.get("title") else "tv"),
                    "title": r.get("title") or r.get("name"),
                    "original_title": r.get("original_title") or r.get("original_name"),
                    "overview": r.get("overview", ""),
                    "poster": (app_state.tmdb.build_image_url(poster, original=False) if poster else ""),
                    "backdrop": (app_state.tmdb.build_image_url(backdrop, original=False) if backdrop else ""),
                    "release_date": r.get("release_date") or r.get("first_air_date"),
                    "vote_average": r.get("vote_average", 0),
                }
            )

        return {"results": items}
    except Exception as e:
        logger.error(f"获取 TMDB 热门失败: {e}")
        return {"results": []}
