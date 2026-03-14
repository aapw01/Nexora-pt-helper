"""
订阅模块单元测试
测试资源选择、订阅管理等功能
"""

from unittest.mock import MagicMock

import pytest

from modules.mteam import TorrentInfo
from modules.store import Store
from modules.subscription import SubscriptionManager


class TestPickBest:
    """测试 _pick_best 资源选择逻辑"""

    @pytest.fixture
    def manager(self):
        """创建测试用订阅管理器"""
        return SubscriptionManager(
            store=MagicMock(),
            tmdb=MagicMock(),
            pt_client=MagicMock(),
            qbit=MagicMock(),
            libraries={},
            notifier=None,
        )

    def _make_torrent(
        self,
        name: str,
        labels: list[str] | None = None,
        seeders: int = 10,
    ) -> TorrentInfo:
        """创建测试用 TorrentInfo"""
        return TorrentInfo(
            id="1",
            name=name,
            size="5GB",
            size_bytes=5368709120,
            seeders=seeders,
            leechers=0,
            category="movie",
            upload_time="2024-01-01",
            labels_new=labels or [],
        )

    def test_pick_single_result(self, manager):
        """单个结果直接返回"""
        results = [self._make_torrent("Movie 1080p")]
        best = manager._pick_best(results)
        assert best.name == "Movie 1080p"

    def test_pick_empty_raises(self, manager):
        """空列表抛出异常"""
        with pytest.raises(ValueError):
            manager._pick_best([])

    def test_prefer_chinese_subtitle(self, manager):
        """优先选择中字"""
        results = [
            self._make_torrent("Movie 1080p", labels=["无字"]),
            self._make_torrent("Movie 1080p 中字", labels=["中字"]),
            self._make_torrent("Movie 4K", labels=["4k"]),
        ]
        best = manager._pick_best(results)
        assert best.tag_subtitle == "中字"

    def test_prefer_chinese_in_name(self, manager):
        """文件名包含中字也应被识别"""
        results = [
            self._make_torrent("Movie 1080p"),
            self._make_torrent("Movie 1080p 中字版"),
        ]
        best = manager._pick_best(results)
        assert "中字" in best.name

    def test_prefer_higher_resolution_when_no_chinese(self, manager):
        """无中字时优先高分辨率"""
        results = [
            self._make_torrent("Movie 720p", labels=["720p"]),
            self._make_torrent("Movie 1080p", labels=["1080p"]),
            self._make_torrent("Movie 4K", labels=["4k"]),
        ]
        best = manager._pick_best(results)
        assert best.tag_resolution == "4K"

    def test_prefer_4k_over_1080p(self, manager):
        """4K 优先于 1080p"""
        results = [
            self._make_torrent("Movie 1080p BluRay", labels=["1080p"]),
            self._make_torrent("Movie 2160p", labels=["4k"]),
        ]
        best = manager._pick_best(results)
        assert best.tag_resolution == "4K"

    def test_prefer_remux_quality(self, manager):
        """同分辨率时 REMUX 优先"""
        results = [
            self._make_torrent("Movie 1080p WEB-DL", labels=["1080p"]),
            self._make_torrent("Movie 1080p REMUX", labels=["1080p"]),
        ]
        best = manager._pick_best(results)
        assert "REMUX" in best.name

    def test_prefer_more_seeders_as_tiebreaker(self, manager):
        """相同条件时做种多的优先"""
        results = [
            self._make_torrent("Movie 1080p", labels=["1080p"], seeders=10),
            self._make_torrent("Movie 1080p Copy", labels=["1080p"], seeders=100),
        ]
        best = manager._pick_best(results)
        assert best.seeders == 100

    def test_chinese_trumps_resolution(self, manager):
        """中字优先级高于分辨率"""
        results = [
            self._make_torrent("Movie 4K HDR", labels=["4k", "hdr10"]),
            self._make_torrent("Movie 1080p 中字", labels=["1080p", "中字"]),
        ]
        best = manager._pick_best(results)
        assert best.tag_subtitle == "中字"
        assert best.tag_resolution == "1080P"


class TestSubscriptionManagerIntegration:
    """测试 SubscriptionManager 集成"""

    @pytest.fixture
    def mock_pt_client(self):
        """模拟 PT 客户端"""
        client = MagicMock()
        client.search.return_value = []
        client.get_download_url.return_value = "https://example.com/download"
        client.download_torrent_file.return_value = (b"torrent_content", "test.torrent")
        return client

    @pytest.fixture
    def mock_store(self):
        """模拟存储"""
        store = MagicMock()
        store.list_pending_items.return_value = []
        return store

    @pytest.fixture
    def manager(self, mock_store, mock_pt_client):
        """创建测试用管理器"""
        return SubscriptionManager(
            store=mock_store,
            tmdb=MagicMock(),
            pt_client=mock_pt_client,
            qbit=MagicMock(),
            libraries={},
            notifier=None,
        )

    def test_manager_uses_pt_client(self, manager, mock_pt_client):
        """测试管理器使用 pt_client 而非 mteam"""
        assert manager.pt_client == mock_pt_client
        assert not hasattr(manager, "mteam")

    def test_process_tv_calls_pt_client(self, manager, mock_store, mock_pt_client):
        """测试处理剧集时调用 PT 客户端"""
        mock_store.list_pending_items.return_value = [{"season": 1, "episode": 1}]
        mock_pt_client.search.return_value = [
            TorrentInfo(
                id="1",
                name="Test Show S01E01 1080p",
                size="1GB",
                size_bytes=1073741824,
                seeders=50,
                leechers=5,
                category="tv",
                upload_time="2024-01-01",
            )
        ]

        sub = {"id": 1, "title": "Test Show", "tmdb_id": "12345"}
        manager._process_tv(sub, max_items=5)

        mock_pt_client.search.assert_called_once()
        mock_pt_client.get_download_url.assert_called_once_with("1")


class TestSubscriptionCompletionStatus:
    """测试订阅完成状态收敛与轮询跳过逻辑"""

    @pytest.fixture
    def store(self, tmp_path):
        return Store(db_path=str(tmp_path / "subscription.db"))

    @pytest.fixture
    def manager(self, store):
        return SubscriptionManager(
            store=store,
            tmdb=MagicMock(),
            pt_client=MagicMock(),
            qbit=MagicMock(),
            libraries={},
            notifier=None,
        )

    def test_list_subscriptions_marks_finished_when_download_complete(self, store, manager):
        sub_id = store.add_subscription(
            tmdb_id="1001",
            sub_type="tv",
            title="Test Show",
            year="2026",
        )
        store.upsert_items(
            sub_id,
            [
                {"season": 1, "episode": 1, "name": "E1", "air_date": "2026-01-01"},
                {"season": 1, "episode": 2, "name": "E2", "air_date": "2026-01-08"},
            ],
        )
        store.mark_item_downloaded(sub_id, 1, 1)
        store.mark_item_downloaded(sub_id, 1, 2)

        subs = manager.list_subscriptions(limit=10)
        sub = next(s for s in subs if s["id"] == sub_id)

        assert sub["total"] == 2
        assert sub["downloaded"] == 2
        assert sub["finished"] is True
        assert sub["status"] == "finished"

        persisted = store.get_subscription(sub_id)
        assert persisted is not None
        assert persisted["finished"] == 1
        assert persisted["status"] == "finished"

    def test_list_subscriptions_resets_to_active_when_not_complete(self, store, manager):
        sub_id = store.add_subscription(
            tmdb_id="1002",
            sub_type="tv",
            title="Test Show 2",
            year="2026",
        )
        store.upsert_items(
            sub_id,
            [
                {"season": 1, "episode": 1, "name": "E1", "air_date": "2026-01-01"},
                {"season": 1, "episode": 2, "name": "E2", "air_date": "2026-01-08"},
            ],
        )
        store.mark_item_downloaded(sub_id, 1, 1)
        store.update_subscription_state(sub_id, finished=True)

        subs = manager.list_subscriptions(limit=10)
        sub = next(s for s in subs if s["id"] == sub_id)

        assert sub["total"] == 2
        assert sub["downloaded"] == 1
        assert sub["finished"] is False
        assert sub["status"] == "active"

        persisted = store.get_subscription(sub_id)
        assert persisted is not None
        assert persisted["finished"] == 0
        assert persisted["status"] == "active"

    def test_poll_and_download_skips_finished_subscription(self, store):
        sub_id = store.add_subscription(
            tmdb_id="1003",
            sub_type="tv",
            title="Skip Show",
            year="2026",
        )
        store.upsert_items(
            sub_id,
            [{"season": 1, "episode": 1, "name": "E1", "air_date": "2026-01-01"}],
        )
        store.mark_item_downloaded(sub_id, 1, 1)

        mock_pt = MagicMock()
        manager = SubscriptionManager(
            store=store,
            tmdb=MagicMock(),
            pt_client=mock_pt,
            qbit=MagicMock(),
            libraries={},
            notifier=None,
        )

        manager.poll_and_download(max_subs=20, max_items_per_sub=5)

        mock_pt.search.assert_not_called()
