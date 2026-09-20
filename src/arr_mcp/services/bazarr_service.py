"""Bazarr HTTP client (Subtitles).

Bazarr is NOT Servarr-based — it is a standalone Python application with its
own REST API on port 6767.  This client implements direct HTTP calls to the
Bazarr API endpoints.

Unlike other arr services in this package, BazarrClient does NOT extend
BaseArrClient because the API surface is fundamentally different (no pagination
in the same style, different auth pattern options, etc.).
"""

from __future__ import annotations

from typing import Any

import httpx

from arr_mcp.constants import DEFAULT_TIMEOUT
from arr_mcp.services.base import build_cloudflare_access_auth


class BazarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT,
        cloudflare_access_client_id: str = "",
        cloudflare_access_client_secret: str = "",
    ) -> None:
        self.name = "Bazarr"
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.cloudflare_access_auth = build_cloudflare_access_auth(
            cloudflare_access_client_id,
            cloudflare_access_client_secret,
        )
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {"X-Api-Key": self.api_key}
            if self.cloudflare_access_auth:
                headers.update(self.cloudflare_access_auth)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, **params: Any) -> Any:
        client = await self._ensure_client()
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, **params: Any) -> Any:
        client = await self._ensure_client()
        resp = await client.post(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── system ────────────────────────────────────────────────────

    async def get_system_status(self) -> dict[str, Any]:
        return await self._get("/api/system/status")  # type: ignore[return-value]

    async def health_check(self) -> dict[str, Any]:
        return await self.get_system_status()

    # ── movies ────────────────────────────────────────────────────

    async def get_movies(self) -> list[dict[str, Any]]:
        return await self._get("/api/movies")  # type: ignore[return-value]

    # ── series / episodes ─────────────────────────────────────────

    async def get_series(self) -> list[dict[str, Any]]:
        return await self._get("/api/series")  # type: ignore[return-value]

    async def get_episodes(self, series_id: int) -> list[dict[str, Any]]:
        return await self._get("/api/episodes", seriesId=series_id)  # type: ignore[return-value]

    # ── wanted (missing subtitles) ────────────────────────────────

    async def get_wanted_movies(self) -> dict[str, Any]:
        return await self._get("/api/movies/wanted")  # type: ignore[return-value]

    async def get_wanted_episodes(self) -> dict[str, Any]:
        return await self._get("/api/episodes/wanted")  # type: ignore[return-value]

    async def get_all_wanted(self) -> dict[str, Any]:
        """Get all movies and episodes with missing subtitles."""
        movies = await self.get_wanted_movies()
        episodes = await self.get_wanted_episodes()
        return {"movies": movies, "episodes": episodes}

    # ── subtitles ─────────────────────────────────────────────────

    async def search_subtitles(
        self,
        episode_id: int | None = None,
        movie_id: int | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if episode_id:
            params["episodeId"] = episode_id
        if movie_id:
            params["movieId"] = movie_id
        if language:
            params["language"] = language
        return await self._get("/api/subtitles", **params)  # type: ignore[return-value]

    async def download_subtitle(
        self,
        subtitle_path: str,
        episode_id: int | None = None,
        movie_id: int | None = None,
        language: str | None = None,
        provider: str | None = None,
        scene_name: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "subtitle": subtitle_path,
        }
        if episode_id:
            params["episodeId"] = episode_id
        if movie_id:
            params["movieId"] = movie_id
        if language:
            params["language"] = language
        if provider:
            params["provider"] = provider
        if scene_name:
            params["sceneName"] = scene_name
        return await self._post("/api/subtitles", **params)  # type: ignore[return-value]

    # ── history ───────────────────────────────────────────────────

    async def get_history(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str = "time",
        sort_direction: str = "descending",
    ) -> dict[str, Any]:
        """Get subtitle download history with pagination support."""
        params: dict[str, Any] = {
            "start": (page - 1) * page_size,
            "length": page_size,
            "order[0][column]": "0" if sort_key == "time" else "1",
            "order[0][dir]": sort_direction.upper(),
        }
        records = await self._get("/api/episodes/history", **params)  # type: ignore[return-value]
        if isinstance(records, dict) and "data" in records:
            # Handle DataTables format response
            return {
                "records": records.get("data", []),
                "totalRecords": records.get("recordsTotal", 0),
                "page": page,
            }
        elif isinstance(records, list):
            # Handle direct array response
            return {
                "records": records[:page_size],
                "totalRecords": len(records),
                "page": page,
            }
        return records

    # ── providers ─────────────────────────────────────────────────

    async def get_providers(self) -> list[dict[str, Any]]:
        return await self._get("/api/providers")  # type: ignore[return-value]

    # ── disk / queue / wanted (not natively supported by Bazarr) ─────

    async def get_diskspace(self) -> list[dict[str, Any]]:
        """Bazarr does not expose disk space endpoints; returns empty list."""
        return []

    async def get_queue(
        self,
        page: int = 1,
        page_size: int = 20,
        include_unknown: bool = True,
    ) -> dict[str, Any]:
        """Bazarr does not expose a queue endpoint; returns empty queue structure."""
        return {"records": [], "totalRecords": 0, "page": page}

    async def get_wanted_missing(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_key: str = "title",
        sort_direction: str = "ascending",
        monitored: bool = True,
    ) -> dict[str, Any]:
        """Bazarr does not expose wanted/missing endpoints; returns empty structure."""
        return {"records": [], "totalRecords": 0, "page": page}

    # ── languages ─────────────────────────────────────────────────

    async def get_languages(self) -> list[dict[str, Any]]:
        """Bazarr does not expose a languages endpoint; returns empty list."""
        return []
