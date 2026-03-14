"""
对齐 MoviePilot themoviedb/scraper.py 的 NFO 生成。
支持：电影 nfo、电视剧 nfo、季 nfo、集 nfo。
"""

from __future__ import annotations

from typing import Any
from xml.dom import minidom


def _add_node(doc: minidom.Document, parent, name: str, value: str = ""):
    node = doc.createElement(name)
    if value is not None:
        node.appendChild(doc.createTextNode(str(value)))
    parent.appendChild(node)
    return node


def _add_cdata(doc: minidom.Document, parent, name: str, value: str = ""):
    node = doc.createElement(name)
    node.appendChild(doc.createCDATASection(value or ""))
    parent.appendChild(node)
    return node


def gen_movie_nfo(
    tmdbid: int,
    title: str,
    original_title: str = "",
    year: str = "",
    overview: str = "",
    rating: float = 0,
    genres: list[str] | None = None,
    runtime: int = 0,
    directors: list[str] | None = None,
    actors: list[dict[str, str]] | None = None,
) -> str:
    """
    生成电影 NFO 文件内容（对齐 MoviePilot TmdbScraper.__gen_movie_nfo_file）
    """
    doc = minidom.Document()
    root = doc.createElement("movie")
    doc.appendChild(root)

    # uniqueid
    uid = _add_node(doc, root, "uniqueid", str(tmdbid))
    uid.setAttribute("type", "tmdb")
    uid.setAttribute("default", "true")

    _add_node(doc, root, "tmdbid", str(tmdbid))
    _add_node(doc, root, "title", title or "")
    _add_node(doc, root, "originaltitle", original_title or "")
    _add_node(doc, root, "year", year or "")
    _add_cdata(doc, root, "plot", overview or "")
    _add_cdata(doc, root, "outline", overview or "")
    _add_node(doc, root, "rating", str(rating or 0))
    _add_node(doc, root, "runtime", str(runtime or 0))

    # genres
    for g in genres or []:
        _add_node(doc, root, "genre", g)

    # directors
    for d in directors or []:
        _add_node(doc, root, "director", d)

    # actors
    for actor in actors or []:
        xactor = _add_node(doc, root, "actor")
        _add_node(doc, xactor, "name", actor.get("name", ""))
        _add_node(doc, xactor, "role", actor.get("character", ""))
        _add_node(doc, xactor, "thumb", actor.get("profile_path", ""))

    return doc.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def gen_tv_nfo(
    tmdbid: int,
    title: str,
    original_title: str = "",
    year: str = "",
    overview: str = "",
    rating: float = 0,
    genres: list[str] | None = None,
) -> str:
    """
    生成电视剧 NFO 文件内容（tvshow.nfo，对齐 MoviePilot）
    """
    doc = minidom.Document()
    root = doc.createElement("tvshow")
    doc.appendChild(root)

    uid = _add_node(doc, root, "uniqueid", str(tmdbid))
    uid.setAttribute("type", "tmdb")
    uid.setAttribute("default", "true")

    _add_node(doc, root, "tmdbid", str(tmdbid))
    _add_node(doc, root, "title", title or "")
    _add_node(doc, root, "originaltitle", original_title or "")
    _add_node(doc, root, "year", year or "")
    _add_cdata(doc, root, "plot", overview or "")
    _add_cdata(doc, root, "outline", overview or "")
    _add_node(doc, root, "rating", str(rating or 0))

    for g in genres or []:
        _add_node(doc, root, "genre", g)

    return doc.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def gen_tv_season_nfo(seasoninfo: dict[str, Any], season: int) -> str:
    """
    参考 MoviePilot TmdbScraper.__gen_tv_season_nfo_file
    """
    doc = minidom.Document()
    root = doc.createElement("season")
    doc.appendChild(root)

    overview = seasoninfo.get("overview") or ""
    _add_cdata(doc, root, "plot", overview)
    _add_cdata(doc, root, "outline", overview)
    _add_node(doc, root, "title", seasoninfo.get("name") or f"季 {season}")
    _add_node(doc, root, "premiered", seasoninfo.get("air_date") or "")
    _add_node(doc, root, "releasedate", seasoninfo.get("air_date") or "")
    _add_node(doc, root, "year", (seasoninfo.get("air_date") or "")[:4])
    _add_node(doc, root, "seasonnumber", str(season))

    return doc.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def gen_tv_episode_nfo(tmdbid: int, episodeinfo: dict[str, Any], season: int, episode: int) -> str:
    """
    参考 MoviePilot TmdbScraper.__gen_tv_episode_nfo_file（简化：演员/导演字段不全量搬）
    """
    doc = minidom.Document()
    root = doc.createElement("episodedetails")
    doc.appendChild(root)

    # uniqueid (tmdb episode id)
    uid = _add_node(doc, root, "uniqueid", str(episodeinfo.get("id") or ""))
    uid.setAttribute("type", "tmdb")
    uid.setAttribute("default", "true")

    _add_node(doc, root, "tmdbid", str(tmdbid))
    _add_node(doc, root, "title", episodeinfo.get("name") or f"第 {episode} 集")

    overview = episodeinfo.get("overview") or ""
    _add_cdata(doc, root, "plot", overview)
    _add_cdata(doc, root, "outline", overview)

    _add_node(doc, root, "aired", episodeinfo.get("air_date") or "")
    _add_node(doc, root, "year", (episodeinfo.get("air_date") or "")[:4])
    _add_node(doc, root, "season", str(season))
    _add_node(doc, root, "episode", str(episode))
    _add_node(doc, root, "rating", str(episodeinfo.get("vote_average") or "0"))

    return doc.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
