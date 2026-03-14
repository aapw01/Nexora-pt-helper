"""
TMDB 客户端（参考 MoviePilot TmdbScraper/TmdbApi 的职责划分）：
- 优先通过 imdb_id -> /find 查 tmdb_id（最准确）
- 否则通过 title/year 搜索 movie 或 tv
- 根据 tmdb_id 拉详情、季、集信息
- 获取中文/英文双语标题（对齐 MoviePilot __update_tmdbinfo_cn_title / __update_tmdbinfo_extra_title）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class TmdbConfig:
    api_key: str
    language: str = "zh-CN"
    image_domain: str = "image.tmdb.org"
    scrap_original_image: bool = False


class TmdbError(Exception):
    pass


def _imdb_id_from_url(imdb_url: str) -> str:
    if not imdb_url:
        return ""
    m = re.search(r"(tt\d+)", imdb_url)
    return m.group(1) if m else ""


def _cn_num_to_int(s: str) -> int | None:
    """中文数字转阿拉伯数字"""
    mp = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十") and len(s) == 2:
        return 10 + mp.get(s[1], 0)
    if len(s) == 2 and s[1] == "十":
        return mp.get(s[0], 0) * 10
    if len(s) == 3 and s[1] == "十":
        return mp.get(s[0], 0) * 10 + mp.get(s[2], 0)
    return mp.get(s)


def normalize_search_query(query: str) -> dict[str, Any]:
    """
    标准化搜索关键词，去除噪声并提取季号信息

    返回 {"query": str, "season": Optional[int]}

    处理逻辑：
    1. 提取季号（S05 / 第五季 / season 5）
    2. 去除清晰度/来源/编码等噪声（1080p, WEB-DL, x265 等）
    3. 去除特殊符号和多余空格
    """
    raw = (query or "").strip()
    season: int | None = None

    # 提取季号：S05 / S5
    m = re.search(r"(?i)\bS(\d{1,2})\b", raw)
    if m:
        season = int(m.group(1))
        raw = re.sub(r"(?i)\bS\d{1,2}\b", " ", raw)

    # 提取季号：第5季 / 第五季 / 第 十五 季
    m = re.search(r"第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*季", raw)
    if m and season is None:
        season = _cn_num_to_int(m.group(1))
    raw = re.sub(r"第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*季", " ", raw)

    # 提取季号：season 5
    m = re.search(r"(?i)\bseason\s*(\d{1,2})\b", raw)
    if m and season is None:
        season = int(m.group(1))
    raw = re.sub(r"(?i)\bseason\s*\d{1,2}\b", " ", raw)

    # 去除清晰度/来源/编码等噪声
    noise_pattern = (
        r"(?i)\b(2160p|1080p|720p|480p|4k|uhd|hdr|hdr10\+?|dv|dovi|"
        r"web[- ]?dl|webrip|bluray|blu[- ]?ray|x265|h265|hevc|"
        r"x264|h264|aac|ddp|atmos|dts)\b"
    )
    raw = re.sub(noise_pattern, " ", raw)

    # 去除特殊符号
    raw = re.sub(r"[\[\](){}【】]", " ", raw)
    raw = re.sub(r"[._\-]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    return {"query": raw or query.strip(), "season": season}


class TmdbClient:
    def __init__(self, cfg: TmdbConfig):
        self.cfg = cfg
        self.base = "https://api.themoviedb.org/3"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        params["api_key"] = self.cfg.api_key
        params.setdefault("language", self.cfg.language)
        url = f"{self.base}{path}"
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise TmdbError(str(e))

    def find_by_imdb(self, imdb_id: str) -> tuple[str | None, int | None]:
        """
        返回 (type, tmdb_id)，type 为 movie/tv
        """
        if not imdb_id:
            return None, None
        data = self._get(f"/find/{imdb_id}", params={"external_source": "imdb_id"})
        movie_results = data.get("movie_results") or []
        if movie_results:
            return "movie", int(movie_results[0]["id"])
        tv_results = data.get("tv_results") or []
        if tv_results:
            return "tv", int(tv_results[0]["id"])
        return None, None

    def search(self, mtype: str, title: str, year: str | None = None) -> int | None:
        """
        搜索返回 tmdb_id（取第一个结果）。mtype: movie|tv
        统一使用 year 参数：movie 按上映年匹配，tv 按所有 episode 播出年匹配
        （tv 不再用 first_air_date_year，避免"第 N 季年份 ≠ 首播年"导致漏匹配）
        """
        if not title:
            return None
        endpoint = "/search/movie" if mtype == "movie" else "/search/tv"
        params: dict[str, Any] = {"query": title}
        if year:
            params["year"] = year
        data = self._get(endpoint, params=params)
        results = data.get("results") or []
        if not results:
            return None
        return int(results[0]["id"])

    def search_best(
        self,
        mtype: str,
        title: str,
        year: str | None = None,
        season: int | None = None,
        top_n: int = 5,
    ) -> int | None:
        """
        带候选打分的搜索：先按标题(+年份)搜索，再对前 top_n 结果按
        标题精确度、热度打分，选最优候选。

        策略：
        1. 带 year 搜索
        2. 无结果则 fallback 不带 year
        3. 对候选按 original_name/name 精确度 + popularity 打分
        """
        if not title:
            return None

        endpoint = "/search/movie" if mtype == "movie" else "/search/tv"
        query_lower = title.lower().strip()

        candidates: list[dict[str, Any]] = []

        # 第一轮：带年份搜索
        if year:
            data = self._get(endpoint, params={"query": title, "year": year})
            candidates = (data.get("results") or [])[:top_n]

        # 第二轮：无结果则 fallback 不带年份
        if not candidates:
            data = self._get(endpoint, params={"query": title})
            candidates = (data.get("results") or [])[:top_n]

        if not candidates:
            return None
        if len(candidates) == 1:
            return int(candidates[0]["id"])

        # 打分选最优
        best_id = None
        best_score = -1.0

        for r in candidates:
            score = 0.0
            orig = (r.get("original_name") or r.get("original_title") or "").lower().strip()
            name = (r.get("name") or r.get("title") or "").lower().strip()

            if orig == query_lower or name == query_lower:
                score += 100
            elif orig.startswith(query_lower) or name.startswith(query_lower):
                score += 40
            elif query_lower in orig or query_lower in name:
                score += 10

            # 热度加分（归一化到 0~20 范围，避免喧宾夺主）
            popularity = float(r.get("popularity") or 0)
            score += min(popularity / 5.0, 20.0)

            # 投票数加分（归一化到 0~10）
            vote_count = int(r.get("vote_count") or 0)
            score += min(vote_count / 100.0, 10.0)

            if score > best_score:
                best_score = score
                best_id = int(r["id"])

        return best_id

    def search_list(self, title: str, mtype: str | None = None, limit: int = 6) -> list[dict[str, Any]]:
        """
        返回 TMDB 搜索列表，用于订阅交互。
        如果 mtype 为空：movie 与 tv 各取一部分并合并。
        """
        if not title:
            return []

        def _norm_result(r: dict[str, Any], typ: str) -> dict[str, Any]:
            if typ == "movie":
                name = r.get("title") or r.get("name") or ""
                year = (r.get("release_date") or "")[:4]
                original_name = r.get("original_title") or ""
            else:
                name = r.get("name") or r.get("title") or ""
                year = (r.get("first_air_date") or "")[:4]
                original_name = r.get("original_name") or ""
            return {
                "id": int(r.get("id")),
                "type": typ,
                "name": name,
                "original_name": original_name,
                "year": year,
                "overview": r.get("overview") or "",
                "poster_path": r.get("poster_path") or "",
            }

        results: list[dict[str, Any]] = []
        if mtype in (None, "", "movie"):
            data_m = self._get("/search/movie", params={"query": title})
            for r in (data_m.get("results") or [])[:limit]:
                results.append(_norm_result(r, "movie"))
            if mtype == "movie":
                return results[:limit]

        if mtype in (None, "", "tv"):
            data_tv = self._get("/search/tv", params={"query": title})
            for r in (data_tv.get("results") or [])[:limit]:
                results.append(_norm_result(r, "tv"))
            if mtype == "tv":
                return results[:limit]

        # 若无指定类型，混合后截断
        return results[:limit]

    def search_multi(self, query: str) -> list[dict]:
        """混合搜索"""
        results = self._get("/search/multi", params={"query": query})
        return results.get("results", [])

    def trending_all(self, time_window: str = "week") -> list[dict]:
        """获取热门影视（混合）"""
        results = self._get(f"/trending/all/{time_window}")
        return results.get("results", [])

    def trending_movies(self, time_window: str = "week") -> list[dict]:
        """获取热门电影"""
        results = self._get(f"/trending/movie/{time_window}")
        return results.get("results", [])

    def trending_tv(self, time_window: str = "week") -> list[dict]:
        """获取热门剧集"""
        results = self._get(f"/trending/tv/{time_window}")
        return results.get("results", [])

    def search_tv(self, query: str) -> list[dict[str, Any]]:
        """搜索电视剧，返回结果列表"""
        if not query:
            return []
        data = self._get("/search/tv", params={"query": query})
        return data.get("results") or []

    def search_movie(self, query: str) -> list[dict[str, Any]]:
        """搜索电影，返回结果列表"""
        if not query:
            return []
        data = self._get("/search/movie", params={"query": query})
        return data.get("results") or []

    def movie_detail(self, tmdb_id: int, append_to_response: str = "translations,credits") -> dict[str, Any]:
        """
        获取电影详情（含 translations 用于提取多语言标题，credits 用于演员/导演）
        """
        return self._get(f"/movie/{tmdb_id}", params={"append_to_response": append_to_response})

    def tv_detail(self, tmdb_id: int, append_to_response: str = "translations") -> dict[str, Any]:
        """
        获取电视剧详情（含 translations 用于提取多语言标题）
        """
        return self._get(f"/tv/{tmdb_id}", params={"append_to_response": append_to_response})

    def get_movie_images(self, detail: dict[str, Any]) -> dict[str, str]:
        """
        从电影详情中提取图片 URL（对齐 MoviePilot get_metadata_img）
        返回 {filename: url} 字典，如 {"poster.jpg": "https://...", "backdrop.jpg": "https://..."}
        """
        images = {}
        poster = detail.get("poster_path")
        if poster:
            images["poster.jpg"] = self.build_image_url(poster, original=True)
        backdrop = detail.get("backdrop_path")
        if backdrop:
            images["backdrop.jpg"] = self.build_image_url(backdrop, original=True)
        return images

    def get_tv_images(self, detail: dict[str, Any]) -> dict[str, str]:
        """
        从电视剧详情中提取图片 URL
        """
        images = {}
        poster = detail.get("poster_path")
        if poster:
            images["poster.jpg"] = self.build_image_url(poster, original=True)
        backdrop = detail.get("backdrop_path")
        if backdrop:
            images["backdrop.jpg"] = self.build_image_url(backdrop, original=True)
        return images

    def get_season_images(self, season_detail: dict[str, Any], season: int) -> dict[str, str]:
        """
        获取季的图片（对齐 MoviePilot get_season_poster）
        """
        images = {}
        poster = season_detail.get("poster_path")
        if poster:
            sea_seq = str(season).rjust(2, "0")
            filename = "season-specials-poster.jpg" if season == 0 else f"season{sea_seq}-poster.jpg"
            images[filename] = self.build_image_url(poster, original=True)
        return images

    @staticmethod
    def extract_movie_metadata(detail: dict[str, Any]) -> dict[str, Any]:
        """
        从电影详情中提取刮削所需的元数据
        """
        genres = [g.get("name", "") for g in (detail.get("genres") or [])]

        # 演员（取前 10 个）
        credits = detail.get("credits", {})
        cast = credits.get("cast", [])[:10]
        actors = []
        for c in cast:
            actors.append(
                {
                    "name": c.get("name", ""),
                    "character": c.get("character", ""),
                    "profile_path": (
                        f"https://image.tmdb.org/t/p/w185{c.get('profile_path')}" if c.get("profile_path") else ""
                    ),
                }
            )

        # 导演
        crew = credits.get("crew", [])
        directors = [c.get("name", "") for c in crew if c.get("job") == "Director"]

        return {
            "genres": genres,
            "actors": actors,
            "directors": directors,
            "runtime": detail.get("runtime", 0),
            "rating": detail.get("vote_average", 0),
            "overview": detail.get("overview", ""),
        }

    def tv_season_detail(self, tmdb_id: int, season: int) -> dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}/season/{season}")

    def tv_episode_detail(self, tmdb_id: int, season: int, episode: int) -> dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}/season/{season}/episode/{episode}")

    def build_image_url(self, path: str, original: bool = True) -> str:
        if not path:
            return ""
        size = "original" if original else "w780"
        return f"https://{self.cfg.image_domain}/t/p/{size}{path}"

    @staticmethod
    def extract_titles(detail: dict[str, Any], is_movie: bool) -> tuple[str, str]:
        """
        从 TMDB 详情中提取中文标题和英文标题（对齐 MoviePilot）

        - 中文标题（title）：优先使用 API 返回的 title/name（language=zh-CN 时为中文）
        - 英文标题（en_title）：
          - 如果原语言是 en，用 original_title/original_name
          - 否则从 translations 获取 US 地区的标题

        返回 (cn_title, en_title)
        """
        if is_movie:
            cn_title = detail.get("title") or detail.get("name") or ""
            original_title = detail.get("original_title") or ""
            original_lang = detail.get("original_language") or ""
        else:
            cn_title = detail.get("name") or detail.get("title") or ""
            original_title = detail.get("original_name") or ""
            original_lang = detail.get("original_language") or ""

        # 英文标题逻辑（对齐 MoviePilot __update_tmdbinfo_extra_title）
        if original_lang == "en":
            en_title = original_title
        else:
            # 从 translations 获取 US 地区标题
            en_title = ""
            translations = detail.get("translations", {}).get("translations", [])
            for trans in translations:
                if trans.get("iso_3166_1") == "US":
                    data = trans.get("data", {})
                    en_title = data.get("title") if is_movie else data.get("name")
                    break
            # 如果没找到 US 翻译，使用原标题
            if not en_title:
                en_title = original_title

        return cn_title, en_title
