"""
Jinja 命名渲染（对齐你给的 MoviePilot 模板变量）
"""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import Environment


def _format_filesize(bytes_size: int) -> str:
    if bytes_size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_size)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    # MoviePilot 里 fileSize 形如 4.5GB（不带空格）
    if idx >= 2:
        return f"{size:.1f}{units[idx]}"
    return f"{int(size)}{units[idx]}"


def _convert_invalid_characters(s: str) -> str:
    """
    对齐 MoviePilot TemplateContextBuilder.__convert_invalid_characters：
    把文件系统不支持的字符替换为对应的全角字符（例如 ':' -> '：'）
    """
    if not s:
        return s
    invalid_characters = r'\/:*?"<>|'
    halfwidth_chars = "".join([chr(i) for i in range(33, 127)])
    fullwidth_chars = "".join([chr(i + 0xFEE0) for i in range(33, 127)])
    translation_table = str.maketrans(halfwidth_chars, fullwidth_chars)
    for ch in invalid_characters:
        s = s.replace(ch, ch.translate(translation_table))
    return s


@dataclass
class NamingContext:
    # 兼容 MoviePilot 模板变量名
    title: str
    en_title: str = ""
    year: str = ""
    season: int | str | None = None
    season_year: str = ""
    season_episode: str = ""
    episode: int | None = None
    episode_title: str = ""
    part: str = ""
    videoFormat: str = ""
    fileSize: str = ""
    fileExt: str = ""


class JinjaNamer:
    def __init__(self):
        self.env = Environment(autoescape=False)

    def render(self, template: str, ctx: NamingContext) -> str:
        t = self.env.from_string(template)
        return t.render(**ctx.__dict__)

    @staticmethod
    def build_context(
        *,
        title: str,
        en_title: str,
        year: str,
        season: int | str | None,
        season_year: str,
        season_episode: str,
        episode: int | None,
        episode_title: str,
        part: str,
        videoFormat: str,
        file_bytes: int,
        file_ext: str,
    ) -> NamingContext:
        return NamingContext(
            title=_convert_invalid_characters(title or ""),
            en_title=_convert_invalid_characters(en_title or ""),
            year=year or "",
            season=season,
            season_year=season_year or "",
            season_episode=season_episode or "",
            episode=episode,
            episode_title=_convert_invalid_characters(episode_title or ""),
            part=part or "",
            videoFormat=videoFormat or "",
            fileSize=_format_filesize(file_bytes),
            fileExt=(file_ext if file_ext.startswith(".") else f".{file_ext}" if file_ext else ""),
        )
