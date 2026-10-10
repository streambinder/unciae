"""Unit tests for the immich-album-assets runner."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar, Self

import main
import pytest


class FakeImmich:
    albums: ClassVar[dict[str, list[Any]]] = {}
    instances: ClassVar[list[FakeImmich]] = []

    def __init__(self) -> None:
        self.requested: list[str] = []
        FakeImmich.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def album_assets(self, album_id: str) -> list[Any]:
        self.requested.append(album_id)
        return FakeImmich.albums[album_id]


@pytest.fixture(autouse=True)
def _fake_immich(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImmich.albums = {
        "one": [SimpleNamespace(original_path="/photos/a.jpg")],
        "two": [
            SimpleNamespace(original_path="/photos/b.jpg"),
            SimpleNamespace(original_path="/photos/c.jpg"),
        ],
    }
    FakeImmich.instances = []
    monkeypatch.setattr(main, "Immich", FakeImmich)


def test_main_without_albums_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_main_prints_every_album_asset_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main(["one", "two"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert FakeImmich.instances[0].requested == ["one", "two"]
