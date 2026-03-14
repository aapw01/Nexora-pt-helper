"""
PT 站点抽象接口
支持多站点扩展的统一接口定义
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TorrentResult:
    """
    统一的种子结果格式（站点无关）
    用于跨站点搜索和资源选择
    """

    id: str
    name: str
    size: str
    size_bytes: int
    seeders: int
    leechers: int
    category: str
    upload_time: str
    small_descr: str = ""
    labels: list[str] = field(default_factory=list)

    # 评分/链接（可选）
    douban_url: str = ""
    douban_rating: str = ""
    imdb_url: str = ""
    imdb_rating: str = ""

    # 站点特定信息
    site_name: str = ""
    discount: str = ""
    poster: str = ""  # 封面图片 URL

    # -------- 标签属性 --------

    @property
    def tag_resolution(self) -> str:
        """解析清晰度标签"""
        labels_lower = [str(x).lower() for x in (self.labels or [])]
        if "4k" in labels_lower:
            return "4K"
        for t in ("2160p", "1080p", "720p", "480p"):
            if t in self.name.lower() or t in labels_lower:
                return t.upper()
        return ""

    @property
    def tag_subtitle(self) -> str:
        """字幕标签"""
        labels_set = set(self.labels or [])
        if "中字" in labels_set:
            return "中字"
        if "无字" in labels_set:
            return "无字"
        return ""

    @property
    def tag_hdr(self) -> str:
        """HDR/DV 等标签"""
        labels_lower = [str(x).lower() for x in (self.labels or [])]
        tags = []
        if "hdr10" in labels_lower:
            tags.append("HDR10")
        if "dovi" in labels_lower or "dv" in labels_lower:
            tags.append("DoVi")
        return "/".join(tags)

    @property
    def tag_list_compact(self) -> str:
        """用于 UI 展示的紧凑标签串"""
        tags = []
        if self.tag_subtitle:
            tags.append(self.tag_subtitle)
        if self.tag_resolution:
            tags.append(self.tag_resolution)
        if self.tag_hdr:
            tags.append(self.tag_hdr)
        return " · ".join(tags)

    def format_display(self, index: int) -> str:
        """格式化显示文本"""
        name = self.name[:35] + "..." if len(self.name) > 35 else self.name
        return f"{index}. {name}\n   📦 {self.size} | ⬆️ {self.seeders} | ⬇️ {self.leechers}"


class PTClientError(Exception):
    """PT 站点 API 错误基类"""

    pass


class PTClient(ABC):
    """
    PT 站点抽象基类
    所有 PT 站点客户端必须实现此接口
    """

    @property
    @abstractmethod
    def site_name(self) -> str:
        """站点名称（如 M-Team, HDSky）"""
        pass

    @abstractmethod
    def search(
        self,
        keyword: str,
        category_key: str = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> list[TorrentResult]:
        """
        搜索种子资源

        :param keyword: 搜索关键词
        :param category_key: 类别键名 (movie/tv/music/other/all)
        :param page: 页码 (从 1 开始)
        :param page_size: 每页数量
        :return: TorrentResult 列表
        """
        pass

    @abstractmethod
    def get_download_url(self, torrent_id: str) -> str:
        """
        获取种子下载链接

        :param torrent_id: 种子 ID
        :return: 下载 URL
        """
        pass

    @abstractmethod
    def download_torrent_file(self, download_url: str) -> tuple[bytes, str]:
        """
        下载 .torrent 文件内容

        :param download_url: 下载链接
        :return: (文件内容 bytes, 文件名)
        """
        pass

    @abstractmethod
    def get_category_list(self) -> dict[str, str]:
        """
        获取可选类别列表

        :return: {category_key: category_name}
        """
        pass

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """
        测试 API 连接

        :return: (是否成功, 消息)
        """
        pass

    def to_torrent_result(self, data: Any) -> TorrentResult:
        """
        将站点特定数据转换为统一格式
        子类可覆盖此方法实现自定义转换
        """
        raise NotImplementedError("Subclass must implement to_torrent_result")
