"""
资源识别/解析模块（尽量参考 MoviePilot MetaInfoPath 的思路）：
- 从文件名/目录名提取：title/en_title/year/season/episode/part 等
- 识别 Movie / TV / Bluray
- 提取 videoFormat（分辨率/来源/编码/HDR/字幕等）
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path

_SPLIT_RE = re.compile(r"\.|\s+|\(|\)|\[|]|-|\+|【|】|/|～|;|&|\||#|_|「|」|~")


@dataclass
class ParsedMeta:
    media_type: str  # movie|tv|other|bluray
    title: str
    en_title: str = ""
    year: str = ""
    season: int | None = None
    season_year: str = ""
    episode: int | None = None
    season_episode: str = ""
    episode_title: str = ""
    part: str = ""
    videoFormat: str = ""


def is_bluray_structure(path: Path) -> bool:
    """
    蓝光原盘目录判断（参考 MoviePilot is_bluray_folder 的思路）
    """
    if not path.exists():
        return False
    if path.is_file():
        path = path.parent
    # 常见：BDMV/STREAM
    return (path / "BDMV").exists() and ((path / "BDMV" / "STREAM").exists() or (path / "BDMV" / "PLAYLIST").exists())


def _extract_year(text: str) -> str:
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
    return m.group(1) if m else ""


def _is_year_token(tok: str) -> bool:
    return bool(re.fullmatch(r"(19\d{2}|20\d{2})", tok))


def _is_stop_token(tok: str) -> bool:
    """
    用于截断“片名部分”：
    - 一旦遇到清晰度/来源/编码/音轨/HDR/组名等，后面都不应算作 title/en_title
    """
    t = tok.lower()
    if not t:
        return False
    if re.fullmatch(r"\d{3,4}p", t):
        return True
    if t in {
        "4k",
        "uhd",
        "hdr",
        "hdr10",
        "hdr10+",
        "dovi",
        "dv",
        "dolby",
        "vision",
        "remux",
        "bluray",
        "blu",
        "ray",
        "web",
        "webdl",
        "web-dl",
        "webrip",
        "hdtv",
        "x265",
        "h265",
        "hevc",
        "x264",
        "h264",
        "av1",
        "atmos",
        "truehd",
        "dts",
        "dtshd",
        "dts-hd",
        "aac",
        "flac",
        "ac3",
    }:
        return True
    # 7.1 / 5.1 / 2.0
    if re.fullmatch(r"\d\.\d", t):
        return True
    # 组名通常全大写/数字混合且较短（HDH 等），这里保守一点：遇到纯大写且长度<=6 时可视为 stop
    return bool(re.fullmatch(r"[A-Z0-9]{2,6}", tok))


def _split_tokens(text: str) -> list[str]:
    return [t for t in _SPLIT_RE.split(text) if t]


def _extract_season_episode(text: str) -> tuple[str, int | None]:
    """
    提取 SxxEyy / 第yy集 等
    """
    m = re.search(r"(?i)S(\d{1,2})E(\d{1,3})", text)
    if m:
        s = int(m.group(1))
        e = int(m.group(2))
        return f"S{s:02d}E{e:02d}", e

    m = re.search(r"第\s*(\d{1,3})\s*集", text)
    if m:
        e = int(m.group(1))
        return f"E{e:02d}", e

    # 有些只有 Eyy
    m = re.search(r"(?i)(?:^|\\D)E(\\d{1,3})(?:\\D|$)", text)
    if m:
        e = int(m.group(1))
        return f"E{e:02d}", e

    return "", None


def _extract_season(text: str) -> str:
    # S01 / s1
    m = re.search(r"(?i)S(\d{1,2})(?!\d)", text)
    if m:
        return str(int(m.group(1)))
    # 第 1 季
    m = re.search(r"第\s*(\d{1,2})\s*季", text)
    if m:
        return str(int(m.group(1)))
    return ""


def _extract_part(text: str) -> str:
    # Part1/Part2 或 CD1/CD2
    m = re.search(r"(?i)\bPart\s*(\d+)\b", text)
    if m:
        return f"Part{m.group(1)}"
    m = re.search(r"(?i)\bCD\s*(\d+)\b", text)
    if m:
        return f"CD{m.group(1)}"
    return ""


def _infer_video_format(name: str, labels: list[str] | None = None) -> str:
    """
    对齐 MoviePilot 的 videoFormat（meta.resource_pix）语义：**只返回分辨率**
    例如：2160p / 1080p / 720p。
    其他来源/编码/HDR/字幕等不要拼到 videoFormat，避免同一季出现不同尾巴导致落盘不一致。
    """
    name_l = name.lower()
    if "2160p" in name_l or "4k" in name_l:
        return "2160p"
    for r in ("1080p", "720p", "480p"):
        if r in name_l:
            return r
    # 没识别到就空（模板会自动跳过）
    return ""


def parse_media(
    name: str,
    small_descr: str = "",
    labels_new: list[str] | None = None,
    parent_path: str | None = None,
) -> ParsedMeta:
    """
    从种子名/文件名解析元信息。尽量参考 MoviePilot 的 MetaInfoPath：文件名 + 上级目录名合并识别。
    """
    labels_new = labels_new or []
    combo = name
    if small_descr:
        combo = f"{combo} {small_descr}"

    if parent_path:
        p = Path(parent_path)
        combo = f"{combo} {p.name}"
        # 再合并一级上级目录名（对齐 MoviePilot MetaInfoPath: file + parent + parent.parent）
        with contextlib.suppress(Exception):
            combo = f"{combo} {p.parent.name}"

    year = _extract_year(combo)
    season_episode, episode = _extract_season_episode(combo)
    # season：优先从 SxxEyy 推导（保证唯一性与落盘目录一致），其次再从全文提取
    season: int | None = None
    m = re.search(r"(?i)S(\d{1,2})E(\d{1,3})", combo)
    if m:
        season = int(m.group(1))
    if season is None:
        s = _extract_season(combo)
        season = int(s) if s.isdigit() else None

    # 如果没有解析到 episode，但有 season，尝试用“纯数字文件名”推断集号（整季包常见 01.mkv）
    if episode is None and season is not None:
        stem = Path(name).stem
        if stem.isdigit() and 0 < int(stem) <= 999:
            episode = int(stem)

    # 统一生成 season_episode，保证唯一性与落盘目录一致
    if (
        season is not None
        and episode is not None
        and (not season_episode or not season_episode.lower().startswith("s"))
    ):
        season_episode = f"S{season:02d}E{episode:02d}"

    # 电视剧判定：出现季/集信息
    media_type = "tv" if (season or season_episode or episode) else "movie"

    # 蓝光原盘判定（若给了 parent_path）
    if parent_path and is_bluray_structure(Path(parent_path)):
        media_type = "bluray"

    part = _extract_part(combo)

    # Title/en_title：参考 MoviePilot 的思路：先把“片名部分”从噪声（年份/清晰度/编码/音轨/组名...）里切出来
    tokens = _split_tokens(name)
    cut = len(tokens)
    for i, tok in enumerate(tokens):
        if _is_year_token(tok) or _is_stop_token(tok):
            cut = i
            break
    head = tokens[:cut] if tokens else []
    # 去掉开头/结尾的空 token
    head = [t for t in head if t]

    # 中文标题与英文标题分离：如果片名里既有中文又有英文，中文作为 title，英文作为 en_title
    zh_head = [t for t in head if re.search(r"[\u4e00-\u9fff]", t)]
    non_zh_head = [t for t in head if not re.search(r"[\u4e00-\u9fff]", t)]

    if zh_head:
        # 中文标题通常不需要点分隔
        title = "".join(zh_head)
        # 英文标题用点连接更贴近常见 PT 命名
        en_title = ".".join(non_zh_head).strip(".")
    else:
        # 纯英文片名：直接用 head（可能包含多词）
        title = ".".join(head).strip(".") if head else (tokens[0] if tokens else name)
        en_title = ""

    videoFormat = _infer_video_format(name=name, labels=labels_new)

    return ParsedMeta(
        media_type=media_type,
        title=title,
        en_title=en_title,
        year=year,
        season=season,
        season_year="",  # 由 TMDB 补齐
        episode=episode,
        season_episode=season_episode,
        episode_title="",  # 由 TMDB 补齐
        part=part,
        videoFormat=videoFormat,
    )
