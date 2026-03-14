"""
整理/刮削主逻辑（轻量版 TransferChain + MediaChain 思路）：
- 扫描 qB 完成任务
- 列文件、过滤
- 解析元信息（meta_parser）
- TMDB 刮削补全（tmdb_client）
- Jinja 渲染目标路径（jinja_naming）
- copy 到 target_root/libraries
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .jinja_naming import JinjaNamer
from .meta_parser import is_bluray_structure, parse_media
from .store import OrganizeRecord, Store
from .tmdb_client import TmdbClient, TmdbConfig
from .tmdb_nfo import gen_movie_nfo, gen_tv_episode_nfo, gen_tv_season_nfo

logger = logging.getLogger(__name__)


class MediaType:
    """媒体类型常量"""

    MOVIE = "movie"
    TV = "tv"


@dataclass
class OrganizeConfig:
    enabled: bool
    mode: str  # auto/manual/both
    interval_minutes: int
    dry_run: bool
    download_root: str
    path_mappings: list[dict[str, str]]
    libraries: dict[str, str]  # 绝对路径
    naming: dict[str, str]
    filters: dict[str, Any]
    tmdb: dict[str, Any]
    strict_id: dict[str, bool] | None = None  # 严格 ID 策略配置


def _safe_join(root: Path, rel: str) -> Path:
    p = root / rel
    # 防止 .. 跳出
    return p.resolve()


def _sanitize_filename(name: str) -> str:
    """
    清理文件名/文件夹名中的特殊字符，确保跨平台兼容性

    替换规则：
    - Windows 不允许的字符: < > : " / \\ | ? *
    - 替换为全角或等价字符，保持可读性
    """
    if not name:
        return name

    # 替换 Windows 不允许的字符
    replacements = {
        "<": "＜",  # 全角小于号
        ">": "＞",  # 全角大于号
        ":": "：",  # 全角冒号
        '"': "'",  # 双引号改为单引号
        "/": "／",  # 全角斜杠
        "\\": "＼",  # 全角反斜杠
        "|": "｜",  # 全角竖线
        "?": "？",  # 全角问号
        "*": "＊",  # 全角星号
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    # 移除前后空格和点（Windows 不允许文件名以点结尾）
    name = name.strip().rstrip(".")

    return name


class Organizer:
    def __init__(self, cfg: OrganizeConfig, store: Store, qbit, mteam=None):
        self.cfg = cfg
        self.store = store
        self.qbit = qbit
        self.namer = JinjaNamer()

        tmdb_cfg = self.cfg.tmdb or {}
        api_key = (tmdb_cfg.get("api_key") or "").strip()
        self.tmdb: TmdbClient | None = None
        if api_key:
            self.tmdb = TmdbClient(
                TmdbConfig(
                    api_key=api_key,
                    language=tmdb_cfg.get("language", "zh-CN"),
                    image_domain=tmdb_cfg.get("image_domain", "image.tmdb.org"),
                    scrap_original_image=bool(tmdb_cfg.get("scrap_original_image", False)),
                )
            )

        self.download_root = Path(self.cfg.download_root).resolve()
        self.path_mappings = self.cfg.path_mappings or []

        # 过滤配置
        f = self.cfg.filters or {}
        self.media_exts = {e.lower() for e in (f.get("media_exts") or [])}
        self.subtitle_exts = {e.lower() for e in (f.get("subtitle_exts") or [])}
        self.exclude_words = [str(x).lower() for x in (f.get("exclude_words") or [])]
        self.min_filesize_mb = int(f.get("min_filesize_mb") or 0)

    def _is_strict_id_enabled(self, media_type: str) -> bool:
        """
        是否启用指定类型的严格 ID 门禁。
        默认开启（enabled/tv/movie 缺省均视为 True）。
        """
        cfg = self.cfg.strict_id or {}
        if not bool(cfg.get("enabled", True)):
            return False
        return bool(cfg.get(media_type, True))

    def _strict_id_missing_reason(
        self,
        media_type: str,
        enrich: dict[str, Any] | None,
    ) -> str | None:
        """
        返回严格 ID 缺失原因；若满足门禁或未启用则返回 None。
        """
        if not self._is_strict_id_enabled(media_type):
            return None

        enrich = enrich or {}

        if media_type == MediaType.TV and not enrich.get("tmdb_id"):
            return "strict_id_missing: tv tmdb_id"
        if media_type == MediaType.MOVIE and not enrich.get("tmdb_id"):
            return "strict_id_missing: movie tmdb_id"
        return None

    @staticmethod
    def _normalize_tv_season_token(dest_rel: str, season: int | None) -> str:
        """
        统一季目录风格：将 `.s2` 归一为 `.s02`。
        仅匹配 `.s{season}` 且后续不是数字的片段，避免误替换。
        """
        if season is None:
            return dest_rel
        if season >= 10:
            return dest_rel
        pattern = re.compile(rf"(?i)(\.s){season}(?!\d)")
        return pattern.sub(rf"\g<1>{season:02d}", dest_rel)

    @staticmethod
    def _prefer_legacy_tv_season_dir(dest_abs: Path, season: int | None) -> tuple[Path, bool]:
        """
        历史兼容：如果旧的 `.s2` 季目录已存在，优先复用旧目录，避免新增 `.s02` 分叉目录。
        """
        if season is None:
            return dest_abs, False
        if season >= 10:
            return dest_abs, False

        padded_token = f".s{season:02d}"
        legacy_token = f".s{season}"
        parent_str = str(dest_abs.parent)
        if padded_token not in parent_str:
            return dest_abs, False

        legacy_parent = Path(parent_str.replace(padded_token, legacy_token))
        legacy_dest = legacy_parent / dest_abs.name
        if legacy_parent.exists():
            return legacy_dest, True
        return dest_abs, False

    def map_qb_path(self, qb_path: str) -> str:
        """
        把 qB 返回的路径映射为本服务容器内可访问的路径。
        按"最长 from 前缀匹配"进行替换。
        """
        p = (qb_path or "").strip()
        if not p:
            return p
        # 规范化
        p = p.replace("\\", "/")

        best_from = ""
        best_to = ""
        for m in self.path_mappings:
            frm = (m.get("from") or "").rstrip("/").replace("\\", "/")
            to = (m.get("to") or "").rstrip("/").replace("\\", "/")
            if not frm or not to:
                continue
            if (p == frm or p.startswith(frm + "/")) and len(frm) > len(best_from):
                best_from = frm
                best_to = to

        if best_from:
            mapped = best_to + p[len(best_from) :]
            return mapped
        # 智能兜底（解决"qB 返回 /downloads/... 但本服务实际挂载在 /Volumes/... "的常见场景）：
        if self.download_root and self.download_root.exists():
            for common_root in ("/downloads", "/data/downloads", "/mnt/downloads"):
                if p == common_root or p.startswith(common_root + "/"):
                    tail = p[len(common_root) :].lstrip("/")
                    candidate = (self.download_root / tail).resolve()
                    if candidate.exists():
                        return str(candidate)
        return p

    def _library_paths(self) -> dict[str, str]:
        libs = self.cfg.libraries or {}
        return {
            MediaType.MOVIE: str(Path(libs.get(MediaType.MOVIE, "/media/Movies")).resolve()),
            MediaType.TV: str(Path(libs.get(MediaType.TV, "/media/TV")).resolve()),
        }

    def _filter_files(self, base_path: Path, files: list[dict[str, Any]]) -> list[Path]:
        """
        过滤出需要整理的媒体文件（参考 MoviePilot TransferChain 过滤策略）
        """
        selected: list[Path] = []
        for f in files or []:
            rel = f.get("name") or f.get("path") or ""
            if not rel:
                continue
            p = (base_path / rel).resolve()
            if not p.exists():
                logger.debug(f"[filter] 文件不存在，跳过: {p}")
                continue
            if p.is_dir():
                continue
            ext = p.suffix.lower()
            if self.media_exts and ext not in self.media_exts and ext not in self.subtitle_exts:
                continue
            name_l = p.name.lower()
            if any(w in name_l for w in self.exclude_words):
                logger.debug(f"[filter] 命中排除词，跳过: {p.name}")
                continue
            if ext in self.media_exts and self.min_filesize_mb:
                size = p.stat().st_size
                if size < self.min_filesize_mb * 1024 * 1024:
                    logger.debug(
                        f"[filter] 体积过小({size / 1024 / 1024:.1f}MB < {self.min_filesize_mb}MB)，跳过: {p.name}"
                    )
                    continue
            if ext in self.media_exts:
                selected.append(p)
        logger.info(f"[organize] _filter_files: 输入 {len(files or [])} 个文件，筛选出 {len(selected)} 个媒体文件")
        return selected

    def _collect_sidecars(self, video_file: Path) -> list[Path]:
        """
        收集同名字幕/外挂文件
        """
        sidecars: list[Path] = []
        stem = video_file.stem
        for f in video_file.parent.iterdir():
            if not f.is_file():
                continue
            if f.stem != stem:
                continue
            if f.suffix.lower() in self.subtitle_exts:
                sidecars.append(f)
        return sidecars

    def _tmdb_enrich(self, parsed, torrent_info: dict[str, Any] | None = None, imdb_url: str = "") -> dict[str, Any]:
        """
        用 TMDB 补全 title/en_title/year/season_year/episode_title（对齐 MoviePilot）

        返回：
        - title, en_title, year, season_year, episode_title
        - tmdb_type, tmdb_id
        - detail: TMDB 详情对象（用于提取图片和演员等）
        """
        if not self.tmdb:
            return {}

        mtype = "tv" if parsed.media_type in ("tv",) else "movie"
        imdb_id = ""
        if imdb_url:
            m = re.search(r"(tt\d+)", imdb_url)
            imdb_id = m.group(1) if m else ""

        tmdb_type = None
        tmdb_id = None
        if imdb_id:
            tmdb_type, tmdb_id = self.tmdb.find_by_imdb(imdb_id)

        if not tmdb_id:
            search_title = parsed.title
            if "." in search_title and not re.search(r"[\u4e00-\u9fff]", search_title):
                search_title = search_title.replace(".", " ").strip()
            # 使用 search_best：带年份搜索 → 无结果自动 fallback 不带年份 → 候选打分选最优
            tmdb_id = self.tmdb.search_best(
                mtype,
                search_title,
                year=parsed.year or None,
                season=parsed.season,
            )
            tmdb_type = mtype if tmdb_id else None

        if not tmdb_id or not tmdb_type:
            logger.warning(f"[tmdb_enrich] TMDB 未找到: title={parsed.title} year={parsed.year}")
            return {}

        is_movie = tmdb_type == "movie"
        d = self.tmdb.movie_detail(tmdb_id) if is_movie else self.tmdb.tv_detail(tmdb_id)

        # 使用对齐 MoviePilot 的标题提取逻辑
        cn_title, en_title = TmdbClient.extract_titles(d, is_movie=is_movie)

        year = ""
        if is_movie:
            if d.get("release_date"):
                year = str(d["release_date"])[:4]
        else:
            if d.get("first_air_date"):
                year = str(d["first_air_date"])[:4]

        season_year = ""
        episode_title = ""
        if not is_movie and parsed.season is not None:
            season_no = int(parsed.season)
            try:
                sd = self.tmdb.tv_season_detail(tmdb_id, season_no)
                if sd.get("air_date"):
                    season_year = str(sd["air_date"])[:4]
                if parsed.episode:
                    ed = self.tmdb.tv_episode_detail(tmdb_id, season_no, int(parsed.episode))
                    episode_title = ed.get("name") or ""
            except Exception as e:
                logger.warning(f"[tmdb_enrich] 获取季/集详情失败: {e}")

        logger.info(
            f"[tmdb_enrich] TMDB matched: tmdb_id={tmdb_id} cn_title={cn_title} en_title={en_title} "
            f"year={year} season_year={season_year} episode_title={episode_title}"
        )

        return {
            "title": cn_title,
            "en_title": en_title,
            "year": year,
            "season_year": season_year,
            "episode_title": episode_title,
            "tmdb_type": tmdb_type,
            "tmdb_id": tmdb_id,
            "detail": d,
        }

    def _download_image(self, url: str, out_path: Path) -> None:
        if not url:
            return
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.get(url, timeout=60, stream=True)
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
        except Exception as e:
            logger.warning(f"[organize] download image failed: {url} -> {out_path}: {e}")

    def _write_text(self, out_path: Path, content: str) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _render_dest(self, media_type: str, ctx: dict[str, Any]) -> str:
        tpl = (self.cfg.naming or {}).get(media_type) or ""
        if not tpl:
            raise ValueError(f"缺少 naming.{media_type} 模板")
        nc = self.namer.build_context(
            title=ctx.get("title", ""),
            en_title=ctx.get("en_title", ""),
            year=ctx.get("year", ""),
            season=ctx.get("season", ""),
            season_year=ctx.get("season_year", ""),
            season_episode=ctx.get("season_episode", ""),
            episode=ctx.get("episode"),
            episode_title=ctx.get("episode_title", ""),
            part=ctx.get("part", ""),
            videoFormat=ctx.get("videoFormat", ""),
            file_bytes=int(ctx.get("file_bytes", 0) or 0),
            file_ext=ctx.get("file_ext", ""),
        )
        rel = self.namer.render(tpl, nc)

        # 清理路径中的特殊字符（统一处理）
        # 分割路径，对每个部分应用清理，然后重新组合
        parts = rel.split("/")
        cleaned_parts = [_sanitize_filename(part) for part in parts if part]
        rel = "/".join(cleaned_parts)

        return rel.strip().lstrip("/").replace("\\", "/")

    def _scrape_movie(self, dest_abs: Path, enrich: dict[str, Any], dry_run: bool = False):
        """
        为电影生成刮削产物：nfo、poster.jpg、backdrop.jpg（对齐 MoviePilot）
        """
        if not self.tmdb or not enrich.get("tmdb_id"):
            return

        tmdb_id = int(enrich["tmdb_id"])
        detail = enrich.get("detail", {})
        movie_dir = dest_abs.parent

        # 1) 电影 NFO（同名 .nfo）
        nfo_path = dest_abs.with_suffix(".nfo")
        if dry_run:
            logger.info(f"[organize] DRY_RUN movie scrape: will_write={nfo_path}")
        else:
            try:
                meta = TmdbClient.extract_movie_metadata(detail)
                cn_title, _en_title = TmdbClient.extract_titles(detail, is_movie=True)
                movie_nfo = gen_movie_nfo(
                    tmdbid=tmdb_id,
                    title=cn_title,
                    original_title=detail.get("original_title", ""),
                    year=enrich.get("year", ""),
                    overview=meta.get("overview", ""),
                    rating=meta.get("rating", 0),
                    genres=meta.get("genres", []),
                    runtime=meta.get("runtime", 0),
                    directors=meta.get("directors", []),
                    actors=meta.get("actors", []),
                )
                self._write_text(nfo_path, movie_nfo)
            except Exception as e:
                logger.warning(f"[organize] movie nfo failed: {e}")

        # 2) 电影图片（poster.jpg, backdrop.jpg 放在电影目录下）
        images = self.tmdb.get_movie_images(detail)
        for img_name, img_url in images.items():
            img_path = movie_dir / img_name
            if dry_run:
                logger.info(f"[organize] DRY_RUN movie scrape: will_write={img_path}")
            else:
                if not img_path.exists():
                    self._download_image(img_url, img_path)

    def _scrape_tv_episode(
        self,
        dest_abs: Path,
        enrich: dict[str, Any],
        season: int,
        episode: int,
        dry_run: bool = False,
    ):
        """
        为电视剧单集生成刮削产物：nfo、jpg、season.nfo（对齐 MoviePilot）
        """
        if not self.tmdb or not enrich.get("tmdb_id"):
            return

        tmdb_id = int(enrich["tmdb_id"])

        if dry_run:
            logger.info(
                f"[organize] DRY_RUN tv scrape: will_write={dest_abs.with_suffix('.nfo')} "
                f"will_write={dest_abs.with_suffix('.jpg')} "
                f"will_write={dest_abs.parent / 'season.nfo'}"
            )
            return

        try:
            ep_detail = self.tmdb.tv_episode_detail(tmdb_id, season, episode)

            # episode nfo（同名 .nfo）
            ep_nfo = gen_tv_episode_nfo(tmdbid=tmdb_id, episodeinfo=ep_detail, season=season, episode=episode)
            self._write_text(dest_abs.with_suffix(".nfo"), ep_nfo)

            # episode thumb（同名 .jpg）
            still_path = ep_detail.get("still_path") or ""
            if still_path:
                img_url = self.tmdb.build_image_url(still_path, original=True)
                self._download_image(img_url, dest_abs.with_suffix(".jpg"))

            # season.nfo（季目录内）
            season_dir = dest_abs.parent
            season_nfo_path = season_dir / "season.nfo"
            if not season_nfo_path.exists():
                season_detail = self.tmdb.tv_season_detail(tmdb_id, season)
                snfo = gen_tv_season_nfo(seasoninfo=season_detail, season=season)
                self._write_text(season_nfo_path, snfo)

                # 季海报
                season_images = self.tmdb.get_season_images(season_detail, season)
                for img_name, img_url in season_images.items():
                    img_path = season_dir / img_name
                    if not img_path.exists():
                        self._download_image(img_url, img_path)

        except Exception as e:
            logger.warning(f"[organize] tv scrape failed for {dest_abs}: {e}")

    def copy_to_library(
        self,
        torrent_hash: str,
        base_path: str,
        files: list[dict[str, Any]],
        torrent_info: dict[str, Any],
    ) -> tuple[int, int, int, int, str, str]:
        """
        复制整理：返回 (成功数, 跳过数, 失败数, 总数, 最后目标目录, 媒体类型)
        """
        # 1) 先把 qB 的路径映射为本容器可访问路径
        mapped_base_path = self.map_qb_path(base_path)
        base = Path(mapped_base_path).resolve()
        logger.info(f"[organize] base_path(qb)={base_path} -> base_path(mapped)={base}")

        # 2) 映射后的路径必须落在 download_root 下
        if not str(base).startswith(str(self.download_root)):
            raise FileNotFoundError(
                f"下载路径不在 organize.download_root 下，无法访问：{base}（download_root={self.download_root}）。"
                f"请检查 docker 挂载与 organize.path_mappings 配置。"
            )
        if not base.exists():
            raise FileNotFoundError(f"下载路径不存在: {base}")

        # 蓝光原盘处理（简化）
        if is_bluray_structure(base):
            pass

        selected = self._filter_files(base, files)
        ok = 0
        skipped = 0
        bad = 0
        total = len(selected)
        last_dest_dir = ""
        last_media_type = ""  # 记录最后一个文件的媒体类型

        libs = self._library_paths()

        for vf in selected:
            ext = vf.suffix
            parsed = parse_media(
                name=vf.name,
                small_descr=torrent_info.get("name", ""),
                labels_new=torrent_info.get("labels_new", []),
                parent_path=str(vf.parent),
            )

            enrich = self._tmdb_enrich(parsed, imdb_url=torrent_info.get("imdb_url", ""))

            if parsed.media_type == "tv":
                media_type = MediaType.TV
            elif parsed.media_type in ("movie", "bluray"):
                media_type = MediaType.MOVIE
            else:
                media_type = MediaType.MOVIE

            strict_reason = self._strict_id_missing_reason(
                media_type=media_type,
                enrich=enrich,
            )
            if strict_reason:
                skipped += 1
                file_rel = str(vf.relative_to(base))
                if not self.cfg.dry_run:
                    self.store.add_record(
                        OrganizeRecord(
                            torrent_hash=torrent_hash,
                            file_rel=file_rel,
                            dest_rel="",
                            status="skipped",
                            message=strict_reason,
                        )
                    )
                logger.warning(f"[organize] SKIP strict-id: src={vf} media_type={media_type} reason={strict_reason}")
                last_media_type = media_type.value if hasattr(media_type, "value") else str(media_type)
                continue

            # 构建 Jinja 上下文
            ctx = {
                "title": enrich.get("title") or parsed.title,
                "en_title": enrich.get("en_title") or parsed.en_title,
                "year": enrich.get("year") or parsed.year,
                "season": parsed.season,
                "season_year": enrich.get("season_year") or parsed.season_year,
                "episode": parsed.episode,
                "season_episode": parsed.season_episode,
                "episode_title": enrich.get("episode_title") or parsed.episode_title,
                "part": parsed.part,
                "videoFormat": parsed.videoFormat,
                "file_bytes": vf.stat().st_size,
                "file_ext": ext,
            }

            # 选择模板类型
            if media_type == MediaType.TV:
                tpl_type = MediaType.TV
            else:
                tpl_type = MediaType.MOVIE

            dest_rel = self._render_dest(tpl_type, ctx)
            if media_type == MediaType.TV:
                dest_rel = self._normalize_tv_season_token(dest_rel, ctx.get("season"))
            logger.debug(f"[organize] render_dest result: {dest_rel}")
            lib_root = Path(libs[media_type]).resolve()
            dest_abs = (lib_root / dest_rel).resolve()
            if media_type == MediaType.TV:
                legacy_dest_abs, reused_legacy = self._prefer_legacy_tv_season_dir(dest_abs, ctx.get("season"))
                if reused_legacy:
                    logger.info(f"[organize] reuse legacy season dir: {legacy_dest_abs.parent}")
                    dest_abs = legacy_dest_abs
                    with contextlib.suppress(Exception):
                        dest_rel = str(dest_abs.relative_to(lib_root)).replace("\\", "/")

            if not str(dest_abs).startswith(str(lib_root)):
                bad += 1
                self.store.add_record(
                    OrganizeRecord(
                        torrent_hash=torrent_hash,
                        file_rel=str(vf),
                        dest_rel=str(dest_rel),
                        status="failed",
                        message="dest 越界",
                    )
                )
                continue

            # 去重检查
            file_rel = str(vf.relative_to(base))
            if not self.cfg.dry_run and self.store.has_record(torrent_hash, file_rel, dest_rel):
                if dest_abs.exists():
                    logger.info(f"[organize] SKIP (already exists): {dest_abs}")
                    skipped += 1
                    last_dest_dir = str(dest_abs.parent)
                    last_media_type = media_type.value if hasattr(media_type, "value") else str(media_type)
                    continue
                else:
                    logger.info(f"[organize] record exists but dest missing, will recopy: {dest_abs}")

            try:
                sidecars = self._collect_sidecars(vf)
                logger.info(
                    f"[organize] {'DRY_RUN ' if self.cfg.dry_run else ''}copy: "
                    f"src={vf} -> dest={dest_abs} | sidecars={len(sidecars)} | "
                    f"media_type={media_type} "
                    f"title={ctx.get('title')} en_title={ctx.get('en_title')} "
                    f"year={ctx.get('year')} season={ctx.get('season')} ep={ctx.get('episode')} "
                    f"season_year={ctx.get('season_year')} episode_title={ctx.get('episode_title')} "
                    f"videoFormat={ctx.get('videoFormat')}"
                )

                if self.cfg.dry_run:
                    # dry_run 输出刮削产物
                    if (
                        media_type == MediaType.TV
                        and self.tmdb
                        and enrich.get("tmdb_id")
                        and ctx.get("season")
                        and ctx.get("episode")
                    ):
                        self._scrape_tv_episode(
                            dest_abs,
                            enrich,
                            int(ctx["season"]),
                            int(ctx["episode"]),
                            dry_run=True,
                        )
                    elif media_type == MediaType.MOVIE and self.tmdb and enrich.get("tmdb_id"):
                        self._scrape_movie(dest_abs, enrich, dry_run=True)
                    ok += 1
                    last_dest_dir = str(dest_abs.parent)
                    last_media_type = media_type.value if hasattr(media_type, "value") else str(media_type)
                    continue

                dest_abs.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(vf, dest_abs)

                # 复制同名字幕
                for sc in sidecars:
                    shutil.copy2(sc, dest_abs.with_suffix(sc.suffix))

                # 刮削产物
                if (
                    media_type == MediaType.TV
                    and self.tmdb
                    and enrich.get("tmdb_id")
                    and ctx.get("season")
                    and ctx.get("episode")
                ):
                    self._scrape_tv_episode(
                        dest_abs,
                        enrich,
                        int(ctx["season"]),
                        int(ctx["episode"]),
                        dry_run=False,
                    )
                elif media_type == MediaType.MOVIE and self.tmdb and enrich.get("tmdb_id"):
                    self._scrape_movie(dest_abs, enrich, dry_run=False)

                self.store.add_record(
                    OrganizeRecord(
                        torrent_hash=torrent_hash,
                        file_rel=file_rel,
                        dest_rel=dest_rel,
                        status="copied",
                    )
                )
                # 标记下载记录已整理（若存在）
                with contextlib.suppress(Exception):
                    self.store.mark_download_organized(torrent_hash)
                ok += 1
                last_dest_dir = str(dest_abs.parent)
                last_media_type = media_type.value if hasattr(media_type, "value") else str(media_type)
            except Exception as e:
                bad += 1
                if not self.cfg.dry_run:
                    self.store.add_record(
                        OrganizeRecord(
                            torrent_hash=torrent_hash,
                            file_rel=file_rel,
                            dest_rel=dest_rel,
                            status="failed",
                            message=str(e),
                        )
                    )
                logger.error(f"[organize] copy failed: src={vf} -> dest={dest_abs} err={e}")

        logger.info(
            f"[organize] 整理完成: ok={ok} skipped={skipped} bad={bad} total={total} "
            f"dest_dir={last_dest_dir} media_type={last_media_type} dry_run={self.cfg.dry_run}"
        )
        return ok, skipped, bad, total, last_dest_dir, last_media_type
