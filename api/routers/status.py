"""
系统状态 API
"""

from fastapi import APIRouter

from api.state import app_state

router = APIRouter()


@router.get("/status")
async def get_status():
    """获取系统状态（各服务连接状态）"""
    status = {
        "mteam": {"connected": False, "message": "未配置"},
        "qbittorrent": {"connected": False, "version": None},
        "tmdb": {"connected": False},
    }

    # 检查 M-Team 连接
    if app_state.mteam:
        try:
            success, message = app_state.mteam.test_connection()
            status["mteam"] = {"connected": success, "message": message}
        except Exception as e:
            status["mteam"] = {"connected": False, "message": str(e)}

    # 检查 qBittorrent 连接
    if app_state.qbit:
        try:
            connected = app_state.qbit.test_connection()
            version = app_state.qbit.get_version() if connected else None
            status["qbittorrent"] = {"connected": connected, "version": version}
        except Exception as e:
            status["qbittorrent"] = {"connected": False, "error": str(e)}

    # 检查 TMDB
    if app_state.tmdb:
        status["tmdb"] = {"connected": True}

    return status
