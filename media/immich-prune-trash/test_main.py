"""Unit tests for the immich-prune-trash runner."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, Self

import main
import pytest


def _asset(asset_id: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(id=asset_id, original_path=path)


class FakeImmich:
    """Search results keyed by the distinguishing filter of each call."""

    pages: ClassVar[dict[str, list[list[SimpleNamespace]]]] = {}
    emptied: int = 0
    close_count: int = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        FakeImmich.close_count += 1

    def search_metadata(self, **filters: Any) -> list[SimpleNamespace]:
        if "trashedBefore" in filters:
            key = "trashed"
        else:
            key = f"library:{filters.get('libraryId')}"
        pages = FakeImmich.pages.get(key, [[]])
        page = int(filters.get("page", 1))
        return pages[page - 1] if page <= len(pages) else []

    def empty_trash(self) -> int:
        return FakeImmich.emptied


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImmich.pages = {}
    FakeImmich.emptied = 0
    FakeImmich.close_count = 0
    monkeypatch.setattr(main, "Immich", FakeImmich)
    monkeypatch.setenv("IMMICH_API_KEY", "test-key")


def test_human_size_scales_through_units() -> None:
    assert main.human_size(0) == "0.00B"
    assert main.human_size(512) == "512.00B"
    assert main.human_size(1024) == "1024.00B"
    assert main.human_size(2048) == "2.00KB"
    assert main.human_size(3 * 1024**2) == "3.00MB"
    assert main.human_size(2 * 1024**3) == "2.00GB"
    assert main.human_size(1024**9) == "1024.00YB"


def test_api_base_and_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMICH_API_BASE", "http://host:2283///")
    assert main.api_base() == "http://host:2283"
    assert main.api_key() == "test-key"


def test_api_base_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMMICH_API_BASE", raising=False)
    assert main.api_base() == "http://localhost:2283"


def test_api_key_missing_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMMICH_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="IMMICH_API_KEY not set"):
        main.api_key()


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_api_request_returns_json_and_sends_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["key"] = request.get_header("X-api-key")
        seen["timeout"] = timeout
        return _FakeResponse(json.dumps([{"id": "l1"}]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert main.api_request("GET", "/libraries") == [{"id": "l1"}]
    assert seen == {
        "url": "http://localhost:2283/api/libraries",
        "method": "GET",
        "key": "test-key",
        "timeout": main.HTTP_TIMEOUT,
    }


def test_api_request_empty_body_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b""))
    assert main.api_request("DELETE", "/assets", {"ids": ["a"]}) is None


def test_api_request_http_error_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_urlopen(request: Any, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError(request.full_url, 503, "down", {}, io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    with pytest.raises(SystemExit, match="HTTP 503"):
        main.api_request("GET", "/libraries")


def test_get_libraries_and_trash_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, Any]] = []

    def fake_request(method: str, path: str, data: Any = None) -> Any:
        calls.append((method, path, data))
        return [{"id": "l1"}]

    monkeypatch.setattr(main, "api_request", fake_request)
    assert main.get_libraries() == [{"id": "l1"}]
    main.trash_assets(["a1"])
    assert calls == [
        ("GET", "/libraries", None),
        ("DELETE", "/assets", {"ids": ["a1"]}),
    ]


def test_paged_search_dedupes_and_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "PAGE_SIZE", 2)
    FakeImmich.pages = {
        "library:lib": [
            [_asset("a", "/a"), _asset("b", "/b")],
            [_asset("b", "/b"), _asset("c", "/c")],
            [_asset("c", "/c")],
        ]
    }
    found = list(main.paged_search(FakeImmich(), libraryId="lib"))
    assert [a.id for a in found] == ["a", "b", "c"]


def test_paged_search_stops_on_short_page() -> None:
    FakeImmich.pages = {"library:lib": [[_asset("a", "/a")]]}
    found = list(main.paged_search(FakeImmich(), libraryId="lib"))
    assert [a.id for a in found] == ["a"]


def test_external_libraries_filters_upload_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "get_libraries",
        lambda: [
            {"id": "up", "importPaths": []},
            {"id": "ext", "importPaths": ["/photos"]},
        ],
    )
    assert [lib["id"] for lib in main.external_libraries()] == ["ext"]


def _library(tmp_path: Path, name: str = "photos") -> dict[str, Any]:
    return {"id": "lib", "name": name, "importPaths": [str(tmp_path)]}


def test_check_mount_guard_rejects_inaccessible_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "gone"
    monkeypatch.setattr(
        main,
        "get_libraries",
        lambda: [{"id": "lib", "name": "x", "importPaths": [str(missing)]}],
    )
    with pytest.raises(SystemExit, match="no import path accessible"):
        main.check_mount_guard(FakeImmich())


def test_check_mount_guard_rejects_mostly_missing_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "get_libraries", lambda: [_library(tmp_path)])
    FakeImmich.pages = {"library:lib": [[_asset("a", str(tmp_path / "gone.jpg"))]]}
    with pytest.raises(SystemExit, match="sampled files exist"):
        main.check_mount_guard(FakeImmich())


def test_check_mount_guard_passes_with_files_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"x")
    monkeypatch.setattr(main, "get_libraries", lambda: [_library(tmp_path)])
    FakeImmich.pages = {"library:lib": [[_asset("a", str(photo))]]}
    libraries = main.check_mount_guard(FakeImmich())
    assert libraries[0]["id"] == "lib"


def test_check_mount_guard_stops_sampling_at_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "GUARD_SAMPLE_SIZE", 2)
    monkeypatch.setattr(main, "get_libraries", lambda: [_library(tmp_path)])
    assets = []
    for i in range(5):
        path = tmp_path / f"{i}.jpg"
        path.write_bytes(b"x")
        assets.append(_asset(f"a{i}", str(path)))
    FakeImmich.pages = {"library:lib": [assets]}
    assert main.check_mount_guard(FakeImmich())[0]["id"] == "lib"


def test_find_orphans_only_managed_missing_files(tmp_path: Path) -> None:
    present = tmp_path / "present.jpg"
    present.write_bytes(b"x")
    assets = [
        _asset("gone", str(tmp_path / "gone.jpg")),
        _asset("present", str(present)),
        _asset("internal", "/usr/src/app/upload/gone.jpg"),
        _asset("rootfile", str(tmp_path)),
    ]
    FakeImmich.pages = {"library:lib": [assets]}
    orphans = main.find_orphans(FakeImmich(), [_library(tmp_path)])
    assert [a.id for a in orphans] == ["gone", "rootfile"]


def _set_argv(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", *args])


def test_main_full_run_deletes_trashes_and_empties(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trashed = tmp_path / "trashed.jpg"
    trashed.write_bytes(b"1234")
    gone = tmp_path / "gone.jpg"
    present = tmp_path / "present.jpg"
    present.write_bytes(b"x")
    monkeypatch.setattr(main, "get_libraries", lambda: [_library(tmp_path)])
    FakeImmich.pages = {
        "trashed": [[_asset("t1", str(trashed)), _asset("t2", str(gone))]],
        "library:lib": [[_asset("keep", str(present)), _asset("o1", str(gone))]],
    }
    FakeImmich.emptied = 7
    trashed_ids: list[list[str]] = []
    monkeypatch.setattr(main, "trash_assets", lambda ids: trashed_ids.append(ids))
    _set_argv(monkeypatch)
    assert main.main() == 0
    assert not trashed.exists()
    assert trashed_ids == [["o1"]]
    out = capsys.readouterr().out
    assert "unregistered 7 assets" in out
    assert "1 orphan assets" in out


def test_main_dry_run_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trashed = tmp_path / "trashed.jpg"
    trashed.write_bytes(b"1234")
    gone = tmp_path / "gone.jpg"
    monkeypatch.setattr(main, "get_libraries", lambda: [_library(tmp_path)])
    present = tmp_path / "present.jpg"
    present.write_bytes(b"x")
    FakeImmich.pages = {
        "trashed": [[_asset("t1", str(trashed))]],
        "library:lib": [[_asset("keep", str(present)), _asset("o1", str(gone))]],
    }
    trashed_ids: list[list[str]] = []
    monkeypatch.setattr(main, "trash_assets", lambda ids: trashed_ids.append(ids))
    _set_argv(monkeypatch, "--dry-run")
    assert main.main() == 0
    assert trashed.exists()
    assert trashed_ids == []
    out = capsys.readouterr().out
    assert "would delete" in out
    assert "would trash" in out
    assert "would empty trash" in out


def test_main_no_prune_orphans_skips_guard_and_pruning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeImmich.pages = {"trashed": [[]]}
    guard_calls: list[int] = []
    monkeypatch.setattr(main, "check_mount_guard", lambda immich: guard_calls.append(1) or [])
    _set_argv(monkeypatch, "--no-prune-orphans")
    assert main.main() == 0
    assert guard_calls == []
    assert "Pruning orphan assets" not in capsys.readouterr().out


def test_main_no_prune_orphans_dry_run_notes_skip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeImmich.pages = {"trashed": [[]]}
    _set_argv(monkeypatch, "--no-prune-orphans", "--dry-run")
    assert main.main() == 0
    assert "orphan pruning disabled" in capsys.readouterr().out


def test_main_batches_orphan_trashing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "TRASH_BATCH_SIZE", 2)
    monkeypatch.setattr(main, "get_libraries", lambda: [_library(tmp_path)])
    assets = [_asset(f"o{i}", str(tmp_path / f"gone{i}.jpg")) for i in range(3)]
    present = tmp_path / "present.jpg"
    present.write_bytes(b"x")
    FakeImmich.pages = {
        "trashed": [[]],
        "library:lib": [[_asset("keep", str(present)), *assets]],
    }
    batches: list[list[str]] = []
    monkeypatch.setattr(main, "trash_assets", lambda ids: batches.append(ids))
    _set_argv(monkeypatch)
    assert main.main() == 0
    assert batches == [["o0", "o1"], ["o2"]]


def test_main_empty_trash_zero_prints_no_unregistered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeImmich.pages = {"trashed": [[]]}
    _set_argv(monkeypatch, "--no-prune-orphans")
    assert main.main() == 0
    assert "unregistered" not in capsys.readouterr().out
