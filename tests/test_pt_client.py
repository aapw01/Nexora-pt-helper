"""
PT Client 模块单元测试
测试种子搜索、下载、解析等核心功能
"""

import pytest

from modules.mteam import MTeamAPIError, MTeamClient, TorrentInfo
from modules.pt_client import PTClient, PTClientError, TorrentResult


class TestTorrentResult:
    """测试 TorrentResult 数据类"""

    def test_basic_attributes(self):
        """测试基本属性"""
        result = TorrentResult(
            id="12345",
            name="Test Movie 2024 1080p BluRay",
            size="8.5GB",
            size_bytes=9126805504,
            seeders=100,
            leechers=10,
            category="movie",
            upload_time="2024-01-01 00:00:00",
        )
        assert result.id == "12345"
        assert result.name == "Test Movie 2024 1080p BluRay"
        assert result.seeders == 100

    def test_tag_resolution_from_name(self):
        """测试从名称解析分辨率"""
        result = TorrentResult(
            id="1",
            name="Movie 2160p HDR",
            size="20GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
        )
        assert result.tag_resolution == "2160P"

        result = TorrentResult(
            id="2",
            name="Movie 1080p BluRay",
            size="10GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
        )
        assert result.tag_resolution == "1080P"

    def test_tag_resolution_from_labels(self):
        """测试从标签解析分辨率"""
        result = TorrentResult(
            id="1",
            name="Movie",
            size="20GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
            labels=["4k", "hdr10"],
        )
        assert result.tag_resolution == "4K"

    def test_tag_subtitle(self):
        """测试字幕标签"""
        result = TorrentResult(
            id="1",
            name="Movie",
            size="10GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
            labels=["中字", "1080p"],
        )
        assert result.tag_subtitle == "中字"

        result_no_sub = TorrentResult(
            id="2",
            name="Movie",
            size="10GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
            labels=["无字"],
        )
        assert result_no_sub.tag_subtitle == "无字"

    def test_tag_hdr(self):
        """测试 HDR 标签"""
        result = TorrentResult(
            id="1",
            name="Movie",
            size="20GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
            labels=["hdr10", "dovi"],
        )
        assert "HDR10" in result.tag_hdr
        assert "DoVi" in result.tag_hdr

    def test_format_display(self):
        """测试格式化显示"""
        result = TorrentResult(
            id="1",
            name="Short Movie",
            size="5GB",
            size_bytes=0,
            seeders=50,
            leechers=5,
            category="movie",
            upload_time="",
        )
        display = result.format_display(1)
        assert "1. Short Movie" in display
        assert "📦 5GB" in display
        assert "⬆️ 50" in display

    def test_format_display_truncates_long_name(self):
        """测试长名称被截断"""
        long_name = "A" * 50  # 超过 35 字符
        result = TorrentResult(
            id="1",
            name=long_name,
            size="5GB",
            size_bytes=0,
            seeders=10,
            leechers=0,
            category="movie",
            upload_time="",
        )
        display = result.format_display(1)
        assert "..." in display


class TestTorrentInfo:
    """测试 M-Team 特定的 TorrentInfo"""

    def test_inherits_from_torrent_result(self):
        """测试 TorrentInfo 继承自 TorrentResult"""
        info = TorrentInfo(
            id="123",
            name="Test",
            size="1GB",
            size_bytes=1073741824,
            seeders=10,
            leechers=5,
            category="movie",
            upload_time="2024-01-01",
        )
        assert isinstance(info, TorrentResult)
        assert info.site_name == "M-Team"

    def test_labels_new_syncs_to_labels(self):
        """测试 labels_new 同步到 labels"""
        info = TorrentInfo(
            id="123",
            name="Test",
            size="1GB",
            size_bytes=1073741824,
            seeders=10,
            leechers=5,
            category="movie",
            upload_time="2024-01-01",
            labels_new=["中字", "1080p"],
        )
        # labels_new 应该被同步到父类的 labels
        assert info.tag_subtitle == "中字"
        assert info.tag_resolution == "1080P"


class TestMTeamClient:
    """测试 MTeamClient"""

    @pytest.fixture
    def client(self):
        """创建测试用客户端"""
        return MTeamClient(
            api_key="test_api_key",
            domain="m-team.io",
            categories_config={
                "movie": {"name": "电影", "ids": [401, 419]},
                "tv": {"name": "剧集", "ids": [402, 403]},
                "all": {"name": "全部", "ids": []},
            },
        )

    def test_inherits_from_pt_client(self, client):
        """测试 MTeamClient 继承自 PTClient"""
        assert isinstance(client, PTClient)

    def test_site_name(self, client):
        """测试站点名称"""
        assert client.site_name == "M-Team"

    def test_get_category_list(self, client):
        """测试获取类别列表"""
        categories = client.get_category_list()
        assert "movie" in categories
        assert categories["movie"] == "电影"
        assert "tv" in categories

    def test_format_size(self, client):
        """测试文件大小格式化"""
        assert client._format_size(1024) == "1.0KB"
        assert client._format_size(1024 * 1024) == "1.0MB"
        assert client._format_size(1024 * 1024 * 1024) == "1.0GB"
        assert client._format_size(1024 * 1024 * 1024 * 1024) == "1.0TB"

    def test_parse_torrent(self, client):
        """测试解析种子数据"""
        raw_data = {
            "id": "123456",
            "name": "Test Movie 2024 1080p",
            "size": 5368709120,  # 5GB
            "status": {"seeders": 50, "leechers": 10, "discount": "free"},
            "category": "movie",
            "createdDate": "2024-01-15 12:00:00",
            "labelsNew": ["中字", "1080p"],
            "smallDescr": "测试描述",
            "douban": "https://movie.douban.com/subject/123",
            "doubanRating": "8.5",
            "imdb": "tt1234567",
            "imdbRating": "7.8",
        }

        info = client._parse_torrent(raw_data)

        assert info.id == "123456"
        assert info.name == "Test Movie 2024 1080p"
        assert info.seeders == 50
        assert info.leechers == 10
        assert info.labels_new == ["中字", "1080p"]
        assert info.small_descr == "测试描述"
        assert info.douban_rating == "8.5"

    def test_parse_torrent_with_missing_fields(self, client):
        """测试解析缺少字段的数据"""
        raw_data = {
            "id": "999",
            "name": "Incomplete Data",
        }

        info = client._parse_torrent(raw_data)

        assert info.id == "999"
        assert info.name == "Incomplete Data"
        assert info.seeders == 0
        assert info.leechers == 0
        assert info.labels_new == []


class TestMTeamAPIError:
    """测试 MTeamAPIError"""

    def test_inherits_from_pt_client_error(self):
        """测试 MTeamAPIError 继承自 PTClientError"""
        error = MTeamAPIError("Test error")
        assert isinstance(error, PTClientError)
        assert str(error) == "Test error"


class TestPTClientInterface:
    """测试 PTClient 接口定义"""

    def test_cannot_instantiate_abstract_class(self):
        """测试不能直接实例化抽象类"""
        with pytest.raises(TypeError):
            PTClient()

    def test_abstract_methods_defined(self):
        """测试抽象方法已定义"""
        abstract_methods = [
            "search",
            "get_download_url",
            "download_torrent_file",
            "get_category_list",
            "test_connection",
            "site_name",
        ]
        for method in abstract_methods:
            assert hasattr(PTClient, method)
