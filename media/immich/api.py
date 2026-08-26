"""Reusable Immich API client.

Thin wrapper over Immich REST API. Reads `IMMICH_API_BASE` and `IMMICH_API_KEY`
from env; both can be overridden per call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, cast

import httpx

DEFAULT_BASE = "http://localhost:2283"


@dataclass(frozen=True)
class Asset:
    id: str
    original_path: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Asset:
        return cls(id=data["id"], original_path=data["originalPath"], raw=data)


class ImmichError(RuntimeError):
    pass


class Immich:
    def __init__(
        self,
        base: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_key = api_key or os.environ.get("IMMICH_API_KEY")
        if not resolved_key:
            raise ImmichError("IMMICH_API_KEY not set")
        resolved_base = (base or os.environ.get("IMMICH_API_BASE") or DEFAULT_BASE).rstrip("/")
        self._client = httpx.Client(
            base_url=f"{resolved_base}/api",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": resolved_key,
            },
            timeout=timeout,
        )

    def __enter__(self) -> Immich:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        response = self._client.request(method, path, **kw)
        response.raise_for_status()
        return response.json() if response.content else None

    def album(self, album_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._request("GET", f"/albums/{album_id}"))

    def album_assets(self, album_id: str) -> list[Asset]:
        return [Asset.from_dict(a) for a in self.album(album_id).get("assets", [])]

    def search_metadata(self, **filters: Any) -> list[Asset]:
        # Immich expects camelCase; pass through as-is
        payload = cast(dict[str, Any], self._request("POST", "/search/metadata", json=filters))
        return [Asset.from_dict(a) for a in payload.get("assets", {}).get("items", [])]

    def empty_trash(self) -> int:
        result = cast(dict[str, Any] | None, self._request("POST", "/trash/empty"))
        return int((result or {}).get("count", 0))

    def run_asset_jobs(self, asset_ids: Iterable[str], job_name: str) -> None:
        self._request(
            "POST",
            "/assets/jobs",
            json={"assetIds": list(asset_ids), "name": job_name},
        )

    def libraries(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._request("GET", "/libraries"))

    def scan_library(self, library_id: str) -> None:
        self._request("POST", f"/libraries/{library_id}/scan")

    def queue_status(self, queue: str) -> dict[str, int]:
        # /queues/{name} added in v2.4.0 (alpha); preferred over deprecated /jobs.
        payload = cast(dict[str, Any], self._request("GET", f"/queues/{queue}"))
        return cast(dict[str, int], payload["statistics"])
