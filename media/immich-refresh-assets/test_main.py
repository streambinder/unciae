"""Unit tests for the immich-refresh-assets runner."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, Self

import main
import pytest


class FakeImmich:
    assets: ClassVar[list[Any]] = []
    jobs: ClassVar[list[tuple[list[str], str]]] = []
    searches: ClassVar[list[dict[str, Any]]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def search_metadata(self, **filters: Any) -> list[Any]:
        FakeImmich.searches.append(filters)
        return FakeImmich.assets

    def run_asset_jobs(self, asset_ids: list[str], job_name: str) -> None:
        FakeImmich.jobs.append((asset_ids, job_name))


@pytest.fixture(autouse=True)
def _fake_immich(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImmich.assets = []
    FakeImmich.jobs = []
    FakeImmich.searches = []
    monkeypatch.setattr(main, "Immich", FakeImmich)


def _asset(asset_id: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(id=asset_id, original_path=path)


def test_resolve_asset_id_matches_full_path(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    fullname = os.path.join(os.path.realpath(str(tmp_path)), "photo.jpg")
    FakeImmich.assets = [
        _asset("other", "/elsewhere/photo.jpg"),
        _asset("hit", fullname),
    ]
    assert main.resolve_asset_id(FakeImmich(), str(photo)) == "hit"
    assert FakeImmich.searches[0]["originalFileName"] == "photo.jpg"


def test_resolve_asset_id_returns_none_without_match(tmp_path: Path) -> None:
    FakeImmich.assets = [_asset("other", "/elsewhere/photo.jpg")]
    assert main.resolve_asset_id(FakeImmich(), str(tmp_path / "photo.jpg")) is None


def test_main_without_files_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_main_launches_every_job_for_resolved_asset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    photo = tmp_path / "photo.jpg"
    fullname = os.path.join(os.path.realpath(str(tmp_path)), "photo.jpg")
    FakeImmich.assets = [_asset("hit", fullname)]
    assert main.main([str(photo)]) == 0
    assert FakeImmich.jobs == [(["hit"], job) for job in main.JOBS]
    assert "hit" in capsys.readouterr().out


def test_main_skips_unresolved_asset(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main([str(tmp_path / "missing.jpg")]) == 0
    assert FakeImmich.jobs == []
    assert "FAIL" in capsys.readouterr().out
