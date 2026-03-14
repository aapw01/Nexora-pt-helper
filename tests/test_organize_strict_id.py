"""
整理严格 ID 模式测试：
- 全类型 strict-id 门禁
- strict 关闭时回退旧逻辑
- The Pitt 两种命名在同一 TMDB 命中下归一到同目录
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from modules.organize import OrganizeConfig, Organizer
from modules.organize_local import LocalOrganizer
from modules.store import Store


def _build_organizer(tmp_path: Path, strict_enabled: bool = True) -> tuple[Organizer, Path]:
    download_root = tmp_path / "downloads"
    movie_root = tmp_path / "media" / "movie"
    tv_root = tmp_path / "media" / "tv"

    download_root.mkdir(parents=True, exist_ok=True)
    movie_root.mkdir(parents=True, exist_ok=True)
    tv_root.mkdir(parents=True, exist_ok=True)

    cfg = OrganizeConfig(
        enabled=True,
        mode="manual",
        interval_minutes=10,
        dry_run=True,
        download_root=str(download_root),
        path_mappings=[],
        libraries={
            "movie": str(movie_root),
            "tv": str(tv_root),
        },
        naming={
            "movie": "{{ title }}{% if year %}.{{ year }}{% endif %}/{{ title }}{{ fileExt }}",
            "tv": (
                "{{ title }}{% if en_title %}.{{ en_title }}{% endif %}.{{ year }}/"
                "{{ title }}.s{{ season }}/{{ title }}.{{ season_episode }}{{ fileExt }}"
            ),
        },
        filters={
            "min_filesize_mb": 0,
            "media_exts": [".mkv"],
            "subtitle_exts": [".srt"],
            "exclude_words": [],
        },
        tmdb={},
        strict_id={
            "enabled": strict_enabled,
            "tv": True,
            "movie": True,
        },
    )
    store = Store(db_path=str(tmp_path / "data" / "organize.db"))
    return Organizer(cfg=cfg, store=store, qbit=MagicMock()), download_root


def _create_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test")
    return path


def _local_preview(organizer: Organizer, source_file: Path, media_type: str = "auto") -> dict:
    local = LocalOrganizer(
        organizer=organizer,
        store=organizer.store,
        allowed_roots=[str(source_file.parent)],
    )
    result = local.preview(source_path=source_file, media_type=media_type)
    assert result.files, "preview result should include file details"
    return result.files[0]


def test_tv_two_naming_variants_use_same_dest_dir_when_tmdb_matches(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(
        return_value={
            "tmdb_id": 252096,
            "title": "匹兹堡医护前线",
            "en_title": "The.Pitt",
            "year": "2026",
            "season_year": "",
            "episode_title": "",
        }
    )

    f1 = _create_file(
        download_root / "[匹兹堡医护前线].The.Pitt.S02.2026.2160p.MAX.WEB-DL.DV.HDR.H265.10bit.DDP.5.1.Atmos-CMCTV.mkv"
    )
    f2 = _create_file(download_root / "The.Pitt.S02.2026.2160p.Max.WEB-DL.HDR.DV.H.265.DDP.5.1.Atmos-FROGWeb.mkv")

    r1 = _local_preview(organizer, f1)
    r2 = _local_preview(organizer, f2)

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    assert r1["dest_dir"] == r2["dest_dir"]
    assert r1["dest_dir"].endswith(".s02")


def test_tv_season_dir_normalized_to_s02_when_no_legacy(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(
        return_value={
            "tmdb_id": 252096,
            "title": "匹兹堡医护前线",
            "en_title": "The.Pitt",
            "year": "2026",
            "season_year": "",
            "episode_title": "",
        }
    )

    tv_file = _create_file(download_root / "The.Pitt.S02E01.2026.1080p.WEB-DL.mkv")
    result = _local_preview(organizer, tv_file, media_type="tv")

    assert result["status"] == "ok"
    assert result["dest_dir"].endswith(".s02")


def test_tv_reuses_legacy_s2_dir_if_exists(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(
        return_value={
            "tmdb_id": 252096,
            "title": "匹兹堡医护前线",
            "en_title": "The.Pitt",
            "year": "2026",
            "season_year": "",
            "episode_title": "",
        }
    )

    legacy_dir = tmp_path / "media" / "tv" / "匹兹堡医护前线.The.Pitt.2026" / "匹兹堡医护前线.s2"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    tv_file = _create_file(download_root / "The.Pitt.S02E02.2026.1080p.WEB-DL.mkv")
    result = _local_preview(organizer, tv_file, media_type="tv")

    assert result["status"] == "ok"
    assert result["dest_dir"].endswith(".s2")


def test_strict_tv_requires_tmdb_id(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(return_value={})

    tv_file = _create_file(download_root / "The.Pitt.S02E01.2026.1080p.WEB-DL.mkv")
    result = _local_preview(organizer, tv_file, media_type="tv")

    assert result["status"] == "skipped"
    assert result["reason"] == "strict_id_missing: tv tmdb_id"


def test_strict_movie_requires_tmdb_id(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(return_value={})

    movie_file = _create_file(download_root / "Dune.Part.Two.2024.2160p.WEB-DL.mkv")
    result = _local_preview(organizer, movie_file, media_type="movie")

    assert result["status"] == "skipped"
    assert result["reason"] == "strict_id_missing: movie tmdb_id"


def test_strict_disabled_falls_back_to_legacy_for_movie(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=False)
    organizer._tmdb_enrich = MagicMock(return_value={})

    movie_file = _create_file(download_root / "Dune.Part.Two.2024.2160p.WEB-DL.mkv")
    result = _local_preview(organizer, movie_file, media_type="movie")

    assert result["status"] == "ok"


def test_copy_to_library_enforces_strict_movie_id(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(return_value={})

    movie_file = _create_file(download_root / "Dune.Part.Two.2024.2160p.WEB-DL.mkv")
    ok, skipped, bad, total, _, _ = organizer.copy_to_library(
        torrent_hash="h1",
        base_path=str(download_root),
        files=[{"name": movie_file.name}],
        torrent_info={"name": "Dune.Part.Two", "small_descr": "", "labels_new": [], "imdb_url": ""},
    )

    assert (ok, skipped, bad, total) == (0, 1, 0, 1)


def test_copy_to_library_enforces_strict_tv_id(tmp_path: Path):
    organizer, download_root = _build_organizer(tmp_path, strict_enabled=True)
    organizer._tmdb_enrich = MagicMock(return_value={})

    tv_file = _create_file(download_root / "The.Pitt.S02E01.2026.1080p.WEB-DL.mkv")
    ok, skipped, bad, total, _, _ = organizer.copy_to_library(
        torrent_hash="h2",
        base_path=str(download_root),
        files=[{"name": tv_file.name}],
        torrent_info={"name": "The.Pitt", "small_descr": "", "labels_new": [], "imdb_url": ""},
    )

    assert (ok, skipped, bad, total) == (0, 1, 0, 1)
