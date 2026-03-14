"""
应用共享状态
独立模块，避免循环导入
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.config import Config
    from modules.mteam import MTeamClient
    from modules.organize import Organizer
    from modules.organize_local import LocalOrganizer
    from modules.organize_queue import OrganizeQueue
    from modules.qbit import QBitClient
    from modules.store import Store
    from modules.subscription import SubscriptionManager
    from modules.tmdb_client import TmdbClient


class AppState:
    """应用状态，保存共享的客户端实例"""

    mteam: "MTeamClient | None" = None
    qbit: "QBitClient | None" = None
    store: "Store | None" = None
    tmdb: "TmdbClient | None" = None
    subscription_manager: "SubscriptionManager | None" = None
    organizer: "Organizer | None" = None
    organize_queue: "OrganizeQueue | None" = None
    local_organizer: "LocalOrganizer | None" = None
    config: "Config | None" = None


app_state = AppState()


def init_app_state(
    mteam: "MTeamClient",
    qbit: "QBitClient",
    store: "Store",
    tmdb: "TmdbClient | None" = None,
    subscription_manager: "SubscriptionManager | None" = None,
    organizer: "Organizer | None" = None,
    organize_queue: "OrganizeQueue | None" = None,
    local_organizer: "LocalOrganizer | None" = None,
    config: "Config | None" = None,
):
    """初始化应用状态，注入共享的客户端实例"""
    app_state.mteam = mteam
    app_state.qbit = qbit
    app_state.store = store
    app_state.tmdb = tmdb
    app_state.subscription_manager = subscription_manager
    app_state.organizer = organizer
    app_state.organize_queue = organize_queue
    app_state.local_organizer = local_organizer
    app_state.config = config
