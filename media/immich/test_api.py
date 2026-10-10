"""Unit tests for the Immich API client.

The HTTP layer is an httpx MockTransport, so every request the client
builds is asserted against a recorded request and a canned response.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from immich import Asset, Immich, ImmichError

ASSET = {"id": "a1", "originalPath": "/photos/a1.jpg"}


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # httpx reads proxy settings from the environment on Client creation;
    # a developer machine proxy must not leak into unit tests.
    for var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)


def _items(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [
        {"id": f"a{i}", "originalPath": f"/photos/a{i}.jpg"} for i in range(start, start + count)
    ]


class Recorder:
    def __init__(self, empty_trash_status: int = 200) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.empty_trash_status = empty_trash_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path == "/api/albums/full":
            return httpx.Response(200, json={"id": "full", "assets": [ASSET]})
        if path == "/api/albums/bare":
            return httpx.Response(200, json={"id": "bare"})
        if path == "/api/search/metadata":
            return self._search(body or {})
        if path == "/api/trash/empty":
            if self.empty_trash_status == 204:
                return httpx.Response(204)
            return httpx.Response(200, json={"count": 3})
        if path == "/api/libraries":
            return httpx.Response(200, json=[{"id": "lib1", "importPaths": ["/photos"]}])
        if path == "/api/queues/library":
            return httpx.Response(200, json={"statistics": {"active": 1, "waiting": 2}})
        if path == "/api/empty":
            return httpx.Response(204)
        return httpx.Response(200, json={})

    @staticmethod
    def _search(body: dict[str, Any]) -> httpx.Response:
        if body.get("mode") == "paged":
            if body.get("page") == 1:
                return httpx.Response(200, json={"assets": {"items": _items(1000)}})
            return httpx.Response(200, json={"assets": {"items": _items(1, start=1000)}})
        if body.get("mode") == "none":
            return httpx.Response(200, json={"assets": {"items": []}})
        return httpx.Response(200, json={"assets": {"items": [ASSET]}})


@contextmanager
def make_client(recorder: Recorder | None = None) -> Iterator[Immich]:
    client = Immich(base="http://example.test/", api_key="secret")
    client._client = httpx.Client(
        base_url="http://example.test/api",
        transport=httpx.MockTransport(recorder or Recorder()),
    )
    try:
        yield client
    finally:
        client._client.close()


def test_asset_from_dict() -> None:
    asset = Asset.from_dict(ASSET)
    assert asset.id == "a1"
    assert asset.original_path == "/photos/a1.jpg"
    assert asset.raw == ASSET


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMMICH_API_KEY", raising=False)
    with pytest.raises(ImmichError, match="IMMICH_API_KEY not set"):
        Immich()


def test_env_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMICH_API_KEY", "from-env")
    monkeypatch.setenv("IMMICH_API_BASE", "http://env.test:1234///")
    with Immich() as client:
        assert str(client._client.base_url) == "http://env.test:1234/api/"
        assert client._client.headers["x-api-key"] == "from-env"
    assert client._client.is_closed


def test_default_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMMICH_API_BASE", raising=False)
    client = Immich(api_key="k")
    assert str(client._client.base_url) == "http://localhost:2283/api/"
    client._client.close()


def test_request_without_content_returns_none() -> None:
    with make_client() as client:
        assert client._request("GET", "/empty") is None


def test_album_and_album_assets() -> None:
    recorder = Recorder()
    with make_client(recorder) as client:
        assert client.album("full")["id"] == "full"
        assets = client.album_assets("full")
        assert [a.id for a in assets] == ["a1"]
        assert client.album_assets("bare") == []
    assert recorder.requests[0][1] == "/api/albums/full"


def test_search_metadata() -> None:
    with make_client() as client:
        assets = client.search_metadata(originalFileName="a1.jpg")
        assert [a.original_path for a in assets] == ["/photos/a1.jpg"]


def test_iter_metadata_single_page() -> None:
    with make_client() as client:
        assert [a.id for a in client.iter_metadata()] == ["a1"]


def test_iter_metadata_empty_first_page() -> None:
    with make_client() as client:
        assert list(client.iter_metadata(mode="none")) == []


def test_iter_metadata_pages_until_short_page() -> None:
    recorder = Recorder()
    with make_client(recorder) as client:
        assets = list(client.iter_metadata(mode="paged"))
    assert len(assets) == 1001
    pages = [body["page"] for _, _, body in recorder.requests if body]
    assert pages == [1, 2]


def test_trash_and_empty_trash() -> None:
    recorder = Recorder()
    with make_client(recorder) as client:
        client.trash_assets(["a1", "a2"])
        assert client.empty_trash() == 3
    delete = next(r for r in recorder.requests if r[0] == "DELETE")
    assert delete[2] == {"ids": ["a1", "a2"]}


def test_empty_trash_without_result_counts_zero() -> None:
    with make_client(Recorder(empty_trash_status=204)) as client:
        assert client.empty_trash() == 0


def test_run_asset_jobs() -> None:
    recorder = Recorder()
    with make_client(recorder) as client:
        client.run_asset_jobs(["a1"], "refresh-metadata")
    assert recorder.requests[-1][2] == {"assetIds": ["a1"], "name": "refresh-metadata"}


def test_libraries_scan_and_queue_status() -> None:
    recorder = Recorder()
    with make_client(recorder) as client:
        assert client.libraries()[0]["id"] == "lib1"
        client.scan_library("lib1")
        assert client.queue_status("library") == {"active": 1, "waiting": 2}
    assert ("POST", "/api/libraries/lib1/scan", None) in recorder.requests
