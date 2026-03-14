"""
本地文件/文件夹整理封装层
- 不依赖 qBittorrent，直接对任意本地路径进行整理
- 复用现有 Organizer 的解析/命名/刮削能力
- 支持 media_type 覆盖（auto/movie/tv）与 move/copy 动作
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .meta_parser import parse_media
from .organize import MediaType, Organizer
from .store import OrganizeRecord, Store

logger = logging.getLogger(__name__)

# macOS/Linux 文件名最大字节数（HFS+/APFS/ext4 都是 255 字节）
MAX_FILENAME_BYTES = 255
# 路径最大字节数（macOS 是 1024，留一些余量）
MAX_PATH_BYTES = 900


def truncate_filename(filename: str, max_bytes: int = MAX_FILENAME_BYTES) -> str:
    """
    截断过长的文件名，保留扩展名

    :param filename: 原始文件名
    :param max_bytes: 最大字节数
    :return: 截断后的文件名
    """
    # 分离文件名和扩展名
    if "." in filename:
        name_part, ext = filename.rsplit(".", 1)
        ext = "." + ext
    else:
        name_part = filename
        ext = ""

    ext_bytes = len(ext.encode("utf-8"))
    available_bytes = max_bytes - ext_bytes - 3  # 留 3 字节给 "..."

    if available_bytes <= 0:
        # 扩展名本身就太长了，直接截断整个文件名
        encoded = filename.encode("utf-8")
        if len(encoded) <= max_bytes:
            return filename
        # 逐字符截断
        result = ""
        for char in filename:
            if len((result + char).encode("utf-8")) > max_bytes - 3:
                return result + "..."
            result += char
        return result

    # 检查是否需要截断
    name_bytes = len(name_part.encode("utf-8"))
    if name_bytes <= available_bytes:
        return filename  # 不需要截断

    # 逐字符截断 name_part
    result = ""
    for char in name_part:
        if len((result + char).encode("utf-8")) > available_bytes:
            break
        result += char

    truncated = result + "..." + ext
    logger.warning(
        f"[truncate] 文件名过长，已截断: {len(filename.encode('utf-8'))} -> {len(truncated.encode('utf-8'))} 字节"
    )
    return truncated


def truncate_path(path: Path, max_bytes: int = MAX_PATH_BYTES) -> Path:
    """
    截断过长的路径，主要截断最后一个目录名或文件名

    :param path: 原始路径
    :param max_bytes: 最大字节数
    :return: 截断后的路径
    """
    path_str = str(path)
    if len(path_str.encode("utf-8")) <= max_bytes:
        return path

    # 先尝试截断文件名
    parent = path.parent
    name = path.name

    # 计算父路径需要的字节
    parent_bytes = len(str(parent).encode("utf-8")) + 1  # +1 for separator
    available_for_name = max_bytes - parent_bytes

    if available_for_name < 50:
        # 父路径本身就太长了，无法处理
        logger.error(f"[truncate] 父路径太长，无法截断: {path}")
        return path

    truncated_name = truncate_filename(name, available_for_name)
    truncated_path = parent / truncated_name

    logger.warning(f"[truncate] 路径过长，已截断文件名: {name} -> {truncated_name}")
    return truncated_path


@dataclass
class LocalOrganizeResult:
    """本地整理结果"""

    ok: int = 0
    skipped: int = 0
    bad: int = 0
    total: int = 0
    dest_dir: str = ""
    media_type: str = ""
    error: str = ""
    # 详细文件列表（用于 dry-run 预览）
    files: list[dict[str, Any]] = field(default_factory=list)


class LocalOrganizer:
    """
    本地文件整理器
    - 不依赖 qB，直接对任意本地路径进行整理
    - 复用 Organizer 的解析/命名/刮削能力
    """

    def __init__(
        self,
        organizer: Organizer,
        store: Store,
        allowed_roots: list[str] | None = None,
    ):
        """
        :param organizer: 现有的 Organizer 实例（复用其 TMDB/命名等能力）
        :param store: 存储实例（记录整理历史）
        :param allowed_roots: 允许操作的根目录列表（安全边界）
        """
        self.organizer = organizer
        self.store = store
        self.allowed_roots = [Path(r).resolve() for r in (allowed_roots or [])]

    def is_path_allowed(self, path: Path) -> bool:
        """检查路径是否在允许范围内"""
        resolved = path.resolve()
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def collect_video_files(self, source_path: Path) -> list[Path]:
        """
        收集视频文件列表
        - 如果是文件：直接返回（如果是视频）
        - 如果是目录：递归收集所有视频文件
        """
        media_exts = self.organizer.media_exts or {
            ".mkv",
            ".mp4",
            ".avi",
            ".ts",
            ".m2ts",
            ".mov",
        }

        if source_path.is_file():
            if source_path.suffix.lower() in media_exts:
                return [source_path]
            return []

        # 目录：递归收集
        files = []
        for f in source_path.rglob("*"):
            if f.is_file() and f.suffix.lower() in media_exts:
                # 过滤 sample/trailer 等
                name_l = f.name.lower()
                if any(w in name_l for w in self.organizer.exclude_words):
                    continue
                # 最小体积过滤
                if self.organizer.min_filesize_mb:
                    size = f.stat().st_size
                    if size < self.organizer.min_filesize_mb * 1024 * 1024:
                        continue
                files.append(f)
        return files

    def collect_sidecars(self, video_file: Path) -> list[Path]:
        """收集同名字幕/外挂文件"""
        subtitle_exts = self.organizer.subtitle_exts or {
            ".srt",
            ".ass",
            ".ssa",
            ".sub",
            ".idx",
        }
        sidecars: list[Path] = []
        stem = video_file.stem
        for f in video_file.parent.iterdir():
            if not f.is_file():
                continue
            if f.stem != stem:
                continue
            if f.suffix.lower() in subtitle_exts:
                sidecars.append(f)
        return sidecars

    def organize(
        self,
        source_path: str | Path,
        mode: Literal["copy", "move"] = "move",
        media_type: Literal["auto", "movie", "tv"] = "auto",
        dry_run: bool = False,
        on_conflict: Literal["skip", "rename", "overwrite"] = "skip",
        source_id: str = "",
    ) -> LocalOrganizeResult:
        """
        执行本地整理

        :param source_path: 源文件或目录路径
        :param mode: 整理动作 copy/move
        :param media_type: 媒体类型 auto/movie/tv
        :param dry_run: 是否只预览不执行
        :param on_conflict: 冲突处理策略
        :param source_id: 来源标识（用于记录追踪）
        :return: 整理结果
        """
        source = Path(source_path).resolve()

        # 安全检查
        if self.allowed_roots and not self.is_path_allowed(source):
            return LocalOrganizeResult(
                error=f"路径不在允许范围内: {source}",
            )

        if not source.exists():
            return LocalOrganizeResult(error=f"路径不存在: {source}")

        # 收集视频文件
        video_files = self.collect_video_files(source)
        if not video_files:
            return LocalOrganizeResult(
                error=f"未找到视频文件: {source}",
                total=0,
            )

        result = LocalOrganizeResult(total=len(video_files))
        libs = self.organizer._library_paths()

        for vf in video_files:
            file_result = self._organize_single_file(
                vf=vf,
                mode=mode,
                media_type_override=media_type,
                dry_run=dry_run,
                on_conflict=on_conflict,
                source_id=source_id,
                libs=libs,
            )

            if file_result.get("status") == "ok":
                result.ok += 1
            elif file_result.get("status") == "skipped":
                result.skipped += 1
            else:
                result.bad += 1

            result.files.append(file_result)

            # 记录最后的目标目录和媒体类型
            if file_result.get("dest_dir"):
                result.dest_dir = file_result["dest_dir"]
            if file_result.get("media_type"):
                result.media_type = file_result["media_type"]

        return result

    def _organize_single_file(
        self,
        vf: Path,
        mode: Literal["copy", "move"],
        media_type_override: Literal["auto", "movie", "tv"],
        dry_run: bool,
        on_conflict: Literal["skip", "rename", "overwrite"],
        source_id: str,
        libs: dict[str, str],
    ) -> dict[str, Any]:
        """
        整理单个视频文件
        复用 Organizer 的解析/命名/刮削能力
        """
        ext = vf.suffix

        # 解析媒体信息
        parsed = parse_media(
            name=vf.name,
            small_descr="",
            labels_new=[],
            parent_path=str(vf.parent),
        )

        enrich: dict[str, Any] = {}

        if media_type_override in ("movie", "tv"):
            media_type = media_type_override
            enrich = self.organizer._tmdb_enrich(parsed, {}, imdb_url="")
        else:
            enrich = self.organizer._tmdb_enrich(parsed, {}, imdb_url="")
            if parsed.media_type == "tv":
                media_type = MediaType.TV
            else:
                media_type = MediaType.MOVIE

        strict_reason = self.organizer._strict_id_missing_reason(
            media_type=media_type,
            enrich=enrich,
        )
        if strict_reason:
            return {
                "status": "skipped",
                "source": str(vf),
                "reason": strict_reason,
                "media_type": media_type,
            }

        # 检查是否识别成功
        identified = False
        if media_type == MediaType.TV:
            # 电视剧必须有 TMDB 数据或至少有标题和季/集信息
            identified = bool(enrich.get("tmdb_id")) or (parsed.title and parsed.season)
        else:
            # 电影必须有 TMDB 数据或至少有标题
            identified = bool(enrich.get("tmdb_id")) or bool(parsed.title)

        # 如果识别失败，返回跳过状态
        if not identified:
            return {
                "status": "skipped",
                "source": str(vf),
                "reason": "识别失败：无法从元数据源获取信息",
                "media_type": media_type,
            }

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

        # 渲染目标路径
        try:
            dest_rel = self.organizer._render_dest(tpl_type, ctx)
            if media_type == MediaType.TV:
                dest_rel = self.organizer._normalize_tv_season_token(dest_rel, ctx.get("season"))
        except Exception as e:
            return {
                "status": "error",
                "source": str(vf),
                "error": f"渲染目标路径失败: {e}",
            }

        lib_root = Path(libs[media_type]).resolve()
        dest_abs = (lib_root / dest_rel).resolve()
        if media_type == MediaType.TV:
            legacy_dest_abs, reused_legacy = self.organizer._prefer_legacy_tv_season_dir(dest_abs, ctx.get("season"))
            if reused_legacy:
                logger.info(f"[organize_local] 复用历史季目录: {legacy_dest_abs.parent}")
                dest_abs = legacy_dest_abs
                with_context = None
                try:
                    with_context = str(dest_abs.relative_to(lib_root)).replace("\\", "/")
                except Exception:
                    with_context = None
                if with_context:
                    dest_rel = with_context

        # 检查并截断过长的文件名/目录名
        # 需要检查所有路径组件，不仅仅是最终文件名
        try:
            rel_parts = dest_abs.relative_to(lib_root).parts
        except ValueError:
            rel_parts = dest_abs.parts

        truncated_parts = []
        any_truncated = False

        for part in rel_parts:
            part_bytes = len(part.encode("utf-8"))
            if part_bytes > MAX_FILENAME_BYTES:
                truncated_part = truncate_filename(part, MAX_FILENAME_BYTES)
                logger.warning(
                    f"[organize_local] 路径组件过长，已截断:\n"
                    f"  原始: {part} ({part_bytes} 字节)\n"
                    f"  截断后: {truncated_part} ({len(truncated_part.encode('utf-8'))} 字节)"
                )
                truncated_parts.append(truncated_part)
                any_truncated = True
            else:
                truncated_parts.append(part)

        if any_truncated:
            dest_abs = lib_root.joinpath(*truncated_parts)
            logger.info(f"[organize_local] 最终目标路径: {dest_abs}")

        # 最终检查
        dest_path_bytes = len(str(dest_abs).encode("utf-8"))
        logger.debug(
            f"[organize_local] 目标路径检查:\n"
            f"  路径: {dest_abs}\n"
            f"  总长度: {dest_path_bytes} 字节 (限制 {MAX_PATH_BYTES})"
        )

        # 安全检查：目标不能越界
        try:
            dest_abs.relative_to(lib_root)
        except ValueError:
            return {
                "status": "error",
                "source": str(vf),
                "dest": str(dest_abs),
                "error": "目标路径越界",
            }

        # 冲突处理
        if dest_abs.exists():
            if on_conflict == "skip":
                return {
                    "status": "skipped",
                    "source": str(vf),
                    "dest": str(dest_abs),
                    "dest_dir": str(dest_abs.parent),
                    "media_type": media_type,
                    "reason": "目标已存在",
                }
            elif on_conflict == "rename":
                # 重命名：在文件名后加序号
                counter = 1
                stem = dest_abs.stem
                suffix = dest_abs.suffix
                while dest_abs.exists():
                    dest_abs = dest_abs.with_name(f"{stem}_{counter}{suffix}")
                    counter += 1
            # overwrite: 不做特殊处理，直接覆盖

        # dry-run 模式
        if dry_run:
            sidecars = self.collect_sidecars(vf)
            return {
                "status": "ok",
                "source": str(vf),
                "dest": str(dest_abs),
                "dest_dir": str(dest_abs.parent),
                "media_type": media_type,
                "dry_run": True,
                "sidecars": [str(s) for s in sidecars],
                "will_scrape": {
                    "nfo": str(dest_abs.with_suffix(".nfo")),
                    "poster": str(dest_abs.parent / "poster.jpg") if media_type == MediaType.MOVIE else None,
                },
            }

        # 实际执行
        try:
            dest_abs.parent.mkdir(parents=True, exist_ok=True)

            # 复制或移动主文件
            if mode == "move":
                shutil.move(str(vf), str(dest_abs))
            else:
                shutil.copy2(vf, dest_abs)

            # 处理同名字幕
            sidecars = self.collect_sidecars(vf)
            for sc in sidecars:
                sc_dest = dest_abs.with_suffix(sc.suffix)
                if mode == "move":
                    shutil.move(str(sc), str(sc_dest))
                else:
                    shutil.copy2(sc, sc_dest)

            # 刮削产物
            if (
                media_type == MediaType.TV
                and self.organizer.tmdb
                and enrich.get("tmdb_id")
                and ctx.get("season")
                and ctx.get("episode")
            ):
                self.organizer._scrape_tv_episode(
                    dest_abs,
                    enrich,
                    int(ctx["season"]),
                    int(ctx["episode"]),
                    dry_run=False,
                )
            elif media_type == MediaType.MOVIE and self.organizer.tmdb and enrich.get("tmdb_id"):
                self.organizer._scrape_movie(dest_abs, enrich, dry_run=False)

            # 记录到数据库
            file_rel = vf.name
            self.store.add_record(
                OrganizeRecord(
                    torrent_hash=source_id or f"local:{vf.parent.name}",
                    file_rel=file_rel,
                    dest_rel=dest_rel,
                    status="copied" if mode == "copy" else "moved",
                )
            )

            return {
                "status": "ok",
                "source": str(vf),
                "dest": str(dest_abs),
                "dest_dir": str(dest_abs.parent),
                "media_type": media_type,
                "mode": mode,
            }

        except Exception as e:
            error_msg = str(e)
            # 添加更详细的错误信息
            if "File name too long" in error_msg or "Errno 63" in error_msg:
                dest_name = dest_abs.name
                dest_name_bytes = len(dest_name.encode("utf-8"))
                error_msg = f"文件名过长 ({dest_name_bytes} 字节，限制 255 字节)。请检查命名模板或手动缩短标题。"
                logger.error(
                    f"[organize_local] 文件名过长:\n"
                    f"  源文件: {vf}\n"
                    f"  目标路径: {dest_abs}\n"
                    f"  目标文件名: {dest_name}\n"
                    f"  文件名字节数: {dest_name_bytes}"
                )
            else:
                logger.error(f"[organize_local] 整理失败: {vf} -> {dest_abs}: {e}")
            return {
                "status": "error",
                "source": str(vf),
                "dest": str(dest_abs),
                "error": error_msg,
            }

    def preview(
        self,
        source_path: str | Path,
        media_type: Literal["auto", "movie", "tv"] = "auto",
    ) -> LocalOrganizeResult:
        """
        预览整理结果（dry-run）

        :param source_path: 源文件或目录路径
        :param media_type: 媒体类型
        :return: 预览结果
        """
        return self.organize(
            source_path=source_path,
            mode="move",  # 预览时 mode 不影响结果
            media_type=media_type,
            dry_run=True,
            on_conflict="skip",
        )
