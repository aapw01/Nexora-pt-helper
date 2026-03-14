"""
M-Team API 封装模块
实现资源搜索和下载链接获取
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import requests

from .pt_client import PTClient, PTClientError, TorrentResult

logger = logging.getLogger(__name__)


@dataclass
class TorrentInfo(TorrentResult):
    """
    M-Team 种子信息
    继承自 TorrentResult，添加站点特定字段
    """

    # M-Team 特定字段（继承 TorrentResult 的所有字段）
    labels_new: list[str] = field(default_factory=list)

    def __post_init__(self):
        # 同步 labels_new 到父类 labels
        if self.labels_new and not self.labels:
            object.__setattr__(self, "labels", self.labels_new)
        if not self.site_name:
            object.__setattr__(self, "site_name", "M-Team")

    def format_display(self, index: int) -> str:
        """格式化显示文本"""
        name = self.name[:35] + "..." if len(self.name) > 35 else self.name
        return f"{index}. {name}\n   📦 {self.size} | ⬆️ {self.seeders} | ⬇️ {self.leechers}"

    @property
    def tag_resolution(self) -> str:
        """解析清晰度标签"""
        labels = [str(x).lower() for x in (self.labels_new or [])]
        if "4k" in labels:
            return "4K"
        for t in ("2160p", "1080p", "720p", "480p"):
            if t in self.name.lower() or t in labels:
                return t.upper()
        return ""

    @property
    def tag_subtitle(self) -> str:
        """字幕标签（粗略）"""
        labels = set(self.labels_new or [])
        if "中字" in labels:
            return "中字"
        if "无字" in labels:
            return "无字"
        return ""

    @property
    def tag_hdr(self) -> str:
        """HDR/DV 等标签"""
        labels_l = [str(x).lower() for x in (self.labels_new or [])]
        tags = []
        if "hdr10" in labels_l:
            tags.append("HDR10")
        if "dovi" in labels_l or "dv" in labels_l:
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


class MTeamClient(PTClient):
    """M-Team API 客户端"""

    @property
    def site_name(self) -> str:
        return "M-Team"

    def __init__(
        self,
        api_key: str,
        domain: str,
        categories_config: dict[str, dict],
        user_agent: str = "MoviePilot",
    ):
        """
        初始化 M-Team 客户端

        :param api_key: M-Team API Key
        :param domain: M-Team 域名 (如 m-team.io)
        :param categories_config: 类别配置字典
        """
        self.api_key = api_key
        self.domain = domain
        self.base_url = f"https://api.{domain}"
        self.categories = categories_config
        self.user_agent = user_agent

        # 默认 JSON 请求头（用于 search 等接口）
        self._headers_json = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self.user_agent,
            "x-api-key": self.api_key,
        }

        # 下载 token 接口请求头：参考 MoviePilot，不要强制 Content-Type: application/json
        self._headers_download = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self.user_agent,
            "x-api-key": self.api_key,
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """
        发送 API 请求

        :param method: HTTP 方法
        :param endpoint: API 端点
        :return: 响应 JSON
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        kwargs.setdefault("headers", self._headers_json)
        kwargs.setdefault("timeout", 30)

        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise MTeamAPIError("请求超时，请稍后重试")
        except requests.exceptions.HTTPError:
            if response.status_code == 401:
                raise MTeamAPIError("API Key 无效或已过期")
            raise MTeamAPIError(f"HTTP 错误: {response.status_code}")
        except requests.exceptions.RequestException as e:
            raise MTeamAPIError(f"网络错误: {e!s}")
        except ValueError:
            raise MTeamAPIError("响应解析失败")

    def get_category_list(self) -> dict[str, str]:
        """
        获取可选类别列表（用于生成按钮）

        :return: {category_key: category_name}
        """
        return {key: val.get("name", key) for key, val in self.categories.items()}

    def search(
        self,
        keyword: str,
        category_key: str = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> list[TorrentInfo]:
        """
        搜索种子资源

        :param keyword: 搜索关键词
        :param category_key: 类别键名 (movie/tv/music/other/all)
        :param page: 页码 (从 1 开始)
        :param page_size: 每页数量
        :return: TorrentInfo 列表
        """
        # 处理 IMDB ID
        if keyword and keyword.lower().startswith("tt"):
            keyword = f"https://www.imdb.com/title/{keyword}"

        # 获取类别 ID 列表
        category_config = self.categories.get(category_key, {})
        category_ids = category_config.get("ids", [])

        # 构建请求参数
        params = {
            "keyword": keyword,
            "categories": category_ids,
            "pageNumber": page,
            "pageSize": page_size,
            "visible": 1,
        }

        if category_key == "music":
            params["mode"] = "music"

        result = self._request("POST", "/api/torrent/search", json=params, headers=self._headers_json)

        if str(result.get("code")) != "0":
            raise MTeamAPIError(result.get("message", "搜索失败"))

        data = result.get("data", {})
        torrents_data = data.get("data", [])

        return [self._parse_torrent(t) for t in torrents_data]

    def _parse_torrent(self, data: dict[str, Any]) -> TorrentInfo:
        """解析种子数据"""
        import logging

        logger = logging.getLogger(__name__)

        raw_id = data.get("id", "")
        logger.info(f"[DEBUG] _parse_torrent: raw_id={raw_id}, type={type(raw_id)}")

        # 计算文件大小
        size_bytes = int(data.get("size", 0))
        size_str = self._format_size(size_bytes)

        status = data.get("status") or {}
        labels_new = data.get("labelsNew") or []
        if not isinstance(labels_new, list):
            labels_new = []

        # 提取图片信息
        # M-Team API 可能返回 image/poster/screenshot 等字段
        poster = ""
        image = data.get("image") or data.get("poster") or ""
        if image:
            poster = image
        # 有些返回是相对路径，有些是完整 URL
        if poster and not poster.startswith("http"):
            poster = f"https://{self.domain}{poster}" if poster.startswith("/") else f"https://{self.domain}/{poster}"

        return TorrentInfo(
            id=str(raw_id),
            name=data.get("name", "未知"),
            small_descr=data.get("smallDescr") or "",
            size=size_str,
            size_bytes=size_bytes,
            seeders=int(status.get("seeders", 0)),
            leechers=int(status.get("leechers", 0)),
            category=data.get("category", ""),
            upload_time=data.get("createdDate", ""),
            labels_new=labels_new,
            douban_url=data.get("douban") or "",
            douban_rating=str(data.get("doubanRating") or ""),
            imdb_url=data.get("imdb") or "",
            imdb_rating=str(data.get("imdbRating") or ""),
            discount=str(status.get("discount") or ""),
            poster=poster,
        )

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}PB"

    def get_download_url(self, torrent_id: str) -> str:
        """
        获取种子下载链接

        :param torrent_id: 种子 ID
        :return: 下载 URL
        """
        # 关键点：参考 MoviePilot，POST + query params 方式传递 id
        # 即：https://api.m-team.io/api/torrent/genDlToken?id=xxxx
        result = self._request(
            "POST",
            "/api/torrent/genDlToken",
            params={"id": torrent_id},
            headers=self._headers_download,
        )

        if str(result.get("code")) != "0":
            raise MTeamAPIError(result.get("message", "获取下载链接失败"))

        download_url = result.get("data")
        if not download_url:
            raise MTeamAPIError("下载链接为空")

        return download_url

    @staticmethod
    def _filename_from_response(resp: requests.Response, fallback: str = "download.torrent") -> str:
        """
        从响应头解析文件名（优先 Content-Disposition）
        """
        disposition = resp.headers.get("content-disposition") or resp.headers.get("Content-Disposition") or ""
        # filename="xxx.torrent" 或 filename*=UTF-8''xxx.torrent
        m = re.search(r"filename\*=\s*UTF-8''([^;]+)", disposition)
        if m:
            return unquote(m.group(1)).strip().strip('"')
        m = re.search(r'filename="?([^"]+)"?', disposition)
        if m:
            return unquote(m.group(1)).split(";")[0].strip().strip('"')
        return fallback

    def download_torrent_file(self, download_url: str) -> tuple[bytes, str]:
        """
        下载 .torrent 文件内容（bytes），并返回文件名
        目的：避免让 qBittorrent 服务器去访问 M-Team 下载链接（可能无外网/DNS 问题）
        """
        try:
            resp = requests.get(
                download_url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "*/*",
                },
                timeout=30,
                allow_redirects=True,
            )
        except Exception as e:
            raise MTeamAPIError(f"下载种子失败: {e}")

        if resp.status_code != 200:
            raise MTeamAPIError(f"下载种子失败: HTTP {resp.status_code}")

        # 有些失败会返回 JSON
        ctype = (resp.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                j = resp.json()
                msg = j.get("message") or j.get("msg") or str(j)
            except Exception:
                msg = resp.text[:200]
            raise MTeamAPIError(f"下载种子返回 JSON: {msg}")

        content = resp.content or b""
        if not content:
            raise MTeamAPIError("下载种子为空")

        # 极少数情况下可能返回 magnet 文本
        if content.startswith(b"magnet:"):
            raise MTeamAPIError("返回了 magnet 链接，当前模式仅支持 torrent 文件上传")

        filename = self._filename_from_response(resp)
        if not filename.endswith(".torrent"):
            filename = f"{filename}.torrent"
        return content, filename

    def test_connection(self) -> tuple[bool, str]:
        """
        测试 API 连接

        :return: (是否成功, 消息)
        """
        try:
            # 使用搜索接口测试，不需要额外参数
            result = self._request(
                "POST",
                "/api/torrent/search",
                json={
                    "keyword": "",
                    "pageNumber": 1,
                    "pageSize": 1,
                },
                headers=self._headers_json,
            )
            if str(result.get("code")) == "0":
                return True, "连接成功"
            return False, result.get("message", "未知错误")
        except MTeamAPIError as e:
            return False, str(e)


class MTeamAPIError(PTClientError):
    """M-Team API 错误"""

    pass
