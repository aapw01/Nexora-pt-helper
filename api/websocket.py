"""
WebSocket 处理模块
实现下载进度实时推送
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.state import app_state

logger = logging.getLogger(__name__)
router = APIRouter()

# 活跃的 WebSocket 连接
active_connections: set[WebSocket] = set()


async def broadcast_message(message: dict):
    """向所有连接的客户端广播消息"""
    if not active_connections:
        return

    data = json.dumps(message, ensure_ascii=False)
    disconnected = set()

    for connection in active_connections:
        try:
            await connection.send_text(data)
        except Exception:
            disconnected.add(connection)

    # 清理断开的连接
    for conn in disconnected:
        active_connections.discard(conn)


async def download_status_broadcaster():
    """后台任务：定期推送下载状态"""
    while True:
        try:
            if active_connections and app_state.qbit:
                # 获取所有活跃下载
                torrents = app_state.qbit.get_torrents(limit=50)

                if torrents:
                    downloads = []
                    for t in torrents:
                        downloads.append(
                            {
                                "hash": t.hash,
                                "name": t.name,
                                "progress": round(t.progress * 100, 1),
                                "state_code": t.state_code,
                                "state_text": t.state_text,
                                "state": t.state_display,
                                "dlspeed": t.dlspeed,
                                "upspeed": t.upspeed,
                                "eta": t.eta,
                            }
                        )

                    await broadcast_message(
                        {
                            "type": "download_update",
                            "data": downloads,
                        }
                    )
        except Exception as e:
            logger.error(f"广播下载状态失败: {e}")

        # 每 2 秒推送一次
        await asyncio.sleep(2)


# 后台任务引用
_broadcaster_task: asyncio.Task | None = None


def start_broadcaster():
    """启动后台广播任务"""
    global _broadcaster_task
    if _broadcaster_task is None:
        _broadcaster_task = asyncio.create_task(download_status_broadcaster())
        logger.info("WebSocket 广播任务已启动")


def stop_broadcaster():
    """停止后台广播任务"""
    global _broadcaster_task
    if _broadcaster_task:
        _broadcaster_task.cancel()
        _broadcaster_task = None
        logger.info("WebSocket 广播任务已停止")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点"""
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"WebSocket 连接建立，当前连接数: {len(active_connections)}")

    # 确保广播任务在运行
    start_broadcaster()

    try:
        while True:
            # 保持连接，处理客户端消息
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                # 可以处理客户端发来的命令，如请求刷新等
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)
        logger.info(f"WebSocket 连接断开，剩余连接数: {len(active_connections)}")
