"""
下载 API 行为测试
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from qbittorrentapi.definitions import TorrentState

from api.routers import downloads as downloads_router
from api.state import app_state
from modules.qbit import TorrentStatus


@pytest.fixture(autouse=True)
def _reset_app_state_qbit():
    """隔离 qbit 全局状态，避免测试间相互影响"""
    original_qbit = app_state.qbit
    original_store = app_state.store
    app_state.store = None
    yield
    app_state.qbit = original_qbit
    app_state.store = original_store


class _QBitListStub:
    def get_torrents_paged(self, **kwargs):
        _ = kwargs
        return (
            [
                TorrentStatus(
                    hash="abc",
                    name="Test",
                    state="pausedDL",
                    progress=0.5,
                    size=1024,
                    downloaded=512,
                    uploaded=0,
                    dlspeed=10,
                    upspeed=0,
                    eta=123,
                    category="tv",
                    save_path="/downloads",
                )
            ],
            1,
        )


@pytest.mark.anyio
async def test_get_downloads_includes_state_code_and_state_text():
    app_state.qbit = _QBitListStub()

    result = await downloads_router.get_downloads()
    first = result["downloads"][0]

    assert first["state_code"] == "pausedDL"
    assert first["state_text"] == "暂停下载"
    assert first["state"] == "暂停下载"


class _QBitControlStub:
    def __init__(self, pause_ok: bool = True, resume_ok: bool = True, delete_ok: bool = True):
        self._pause_ok = pause_ok
        self._resume_ok = resume_ok
        self._delete_ok = delete_ok

    def pause_torrent(self, torrent_hash: str):
        _ = torrent_hash
        return self._pause_ok

    def resume_torrent(self, torrent_hash: str):
        _ = torrent_hash
        return self._resume_ok

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False):
        _ = (torrent_hash, delete_files)
        return self._delete_ok


class _QBitManualStub:
    def __init__(self):
        self.calls: list[dict[str, str | None]] = []

    def add_torrent(self, content: str, save_path: str | None = None, category: str | None = None):
        self.calls.append(
            {
                "content": content,
                "save_path": save_path,
                "category": category,
            }
        )
        return "manual-hash"


@pytest.mark.anyio
async def test_pause_resume_delete_raise_when_qbit_reports_failure():
    app_state.qbit = _QBitControlStub(pause_ok=False, resume_ok=False, delete_ok=False)

    with pytest.raises(HTTPException) as pause_err:
        await downloads_router.pause_download("abc")
    assert pause_err.value.status_code == 500

    with pytest.raises(HTTPException) as resume_err:
        await downloads_router.resume_download("abc")
    assert resume_err.value.status_code == 500

    with pytest.raises(HTTPException) as delete_err:
        await downloads_router.delete_download("abc")
    assert delete_err.value.status_code == 500


@pytest.mark.anyio
async def test_pause_resume_delete_success_path():
    app_state.qbit = _QBitControlStub(pause_ok=True, resume_ok=True, delete_ok=True)

    assert await downloads_router.pause_download("abc") == {"success": True}
    assert await downloads_router.resume_download("abc") == {"success": True}
    assert await downloads_router.delete_download("abc") == {"success": True}


@pytest.mark.anyio
async def test_manual_add_download_supports_magnet_and_http_links():
    app_state.qbit = _QBitManualStub()

    magnet_result = await downloads_router.add_manual_download(
        downloads_router.AddManualDownloadRequest(
            url="magnet:?xt=urn:btih:123456",
            category="tv",
        )
    )
    url_result = await downloads_router.add_manual_download(
        downloads_router.AddManualDownloadRequest(
            url="https://example.com/test.torrent",
            category=None,
        )
    )

    assert magnet_result["success"] is True
    assert magnet_result["hash"] == "manual-hash"
    assert url_result["success"] is True
    assert len(app_state.qbit.calls) == 2
    assert app_state.qbit.calls[0]["content"].startswith("magnet:?")
    assert app_state.qbit.calls[0]["category"] == "tv"
    assert app_state.qbit.calls[1]["content"].startswith("https://")
    assert app_state.qbit.calls[1]["category"] is None


@pytest.mark.anyio
async def test_manual_add_download_rejects_unsupported_scheme():
    app_state.qbit = _QBitManualStub()

    with pytest.raises(HTTPException) as err:
        await downloads_router.add_manual_download(
            downloads_router.AddManualDownloadRequest(
                url="ftp://example.com/test.torrent",
            )
        )
    assert err.value.status_code == 400


def test_torrent_state_text_covers_all_qbit_enum_states():
    """确保 qBittorrent 当前枚举状态都有中文映射"""
    for state in TorrentState:
        status = TorrentStatus(
            hash="abc",
            name="Test",
            state=state.value,
            progress=0,
            size=0,
            downloaded=0,
            uploaded=0,
            dlspeed=0,
            upspeed=0,
            eta=0,
            category="",
            save_path="",
        )
        assert status.state_text != state.value
