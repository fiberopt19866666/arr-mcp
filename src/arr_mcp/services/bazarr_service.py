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

# Bazarr's manual search endpoints (``/api/providers/episodes`` and
# ``/api/providers/movies``) return results for every language in the media's
# language profile and do not accept a language filter.  ``language`` is
# therefore applied client-side using this ISO 639 code → name map.
_SUBTITLE_LANGUAGE_NAMES: dict[str, str] = {
    "ar": "arabic",
    "bg": "bulgarian",
    "ca": "catalan",
    "cs": "czech",
    "da": "danish",
    "de": "german",
    "el": "greek",
    "en": "english",
    "es": "spanish",
    "et": "estonian",
    "fa": "persian",
    "fi": "finnish",
    "fr": "french",
    "he": "hebrew",
    "hi": "hindi",
    "hr": "croatian",
    "hu": "hungarian",
    "id": "indonesian",
    "is": "icelandic",
    "it": "italian",
    "ja": "japanese",
    "ko": "korean",
    "lt": "lithuanian",
    "lv": "latvian",
    "ms": "malay",
    "nb": "norwegian",
    "nl": "dutch",
    "no": "norwegian",
    "pl": "polish",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sk": "slovak",
    "sl": "slovenian",
    "sr": "serbian",
    "sv": "swedish",
    "th": "thai",
    "tr": "turkish",
    "uk": "ukrainian",
    "vi": "vietnamese",
    "zh": "chinese",
}


def _language_matches(result_language: str | None, requested: str) -> bool:
    """Match a Bazarr language name against a requested code or name."""
    if not result_language:
        return False
    result = str(result_language).strip().lower()
    wanted = requested.strip().lower()
    if not wanted:
        return True
    if result == wanted or result.startswith(wanted):
        return True
    mapped = _SUBTITLE_LANGUAGE_NAMES.get(wanted)
    return bool(mapped) and (result == mapped or result.startswith(mapped))


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
        if resp.status_code == 204 or not resp.content:
            return {"success": True}
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
        data = await self._get("/api/episodes", **{"seriesid[]": [series_id]})
        if isinstance(data, dict) and "data" in data:
            return data["data"]  # type: ignore[return-value]
        return data  # type: ignore[return-value]

    async def get_series_id_for_episode(self, episode_id: int) -> int | None:
        """Resolve the Sonarr series id that owns ``episode_id``.

        Bazarr's ``/api/episodes`` accepts an ``episodeid[]`` filter and
        returns ``sonarrSeriesId`` alongside each episode's metadata.
        """
        data = await self._get("/api/episodes", **{"episodeid[]": [episode_id]})
        entries = data.get("data", []) if isinstance(data, dict) else data or []
        if entries:
            return entries[0].get("sonarrSeriesId")
        return None

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
        """Search providers for subtitles of an episode or movie.

        Bazarr exposes manual search on the provider namespace:
        ``/api/providers/episodes?episodeid=`` for episodes and
        ``/api/providers/movies?radarrid=`` for movies.  Neither endpoint
        accepts a language filter, so ``language`` is applied client-side.
        """
        if movie_id:
            data = await self._get("/api/providers/movies", radarrid=movie_id)
        elif episode_id:
            data = await self._get("/api/providers/episodes", episodeid=episode_id)
        else:
            return []

        results = data.get("data", []) if isinstance(data, dict) else data or []
        if language:
            results = [r for r in results if _language_matches(r.get("language"), language)]
        return results  # type: ignore[return-value]

    async def download_subtitle(
        self,
        subtitle_path: str,
        episode_id: int | None = None,
        movie_id: int | None = None,
        language: str | None = None,
        provider: str | None = None,
        scene_name: str | None = None,
    ) -> dict[str, Any]:
        """Download a specific subtitle returned by :meth:`search_subtitles`.

        ``subtitle_path`` is the ``subtitle`` identifier from the search
        results.  Bazarr also requires ``hi``, ``forced`` and
        ``original_format`` for manual downloads; these default to "False"
        when not supplied.  Episode downloads additionally require the Sonarr
        series id, which is resolved from ``/api/episodes``.
        """
        params: dict[str, Any] = {
            "hi": "False",
            "forced": "False",
            "original_format": "False",
            "provider": provider or "",
            "subtitle": subtitle_path,
        }

        if movie_id:
            params["radarrid"] = movie_id
            return await self._post("/api/providers/movies", **params)

        if episode_id:
            series_id = await self.get_series_id_for_episode(episode_id)
            if not series_id:
                return {
                    "success": False,
                    "error": f"Unable to resolve series id for episode {episode_id}",
                }
            params["seriesid"] = series_id
            params["episodeid"] = episode_id
            return await self._post("/api/providers/episodes", **params)

        return {"success": False, "error": "episode_id or movie_id is required"}

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
