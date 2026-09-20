"""Prowlarr HTTP client (Indexer Backbone).

Prowlarr is the indexer backbone of the *arr stack. Unlike other *arr apps it
manages indexers (Usenet/Torrent) and syncs them to Radarr/Sonarr/etc.  Its
``/api/v1/search`` endpoint provides unified search across ALL configured
indexers with category filtering.
"""

from __future__ import annotations

from typing import Any

import httpx

from arr_mcp.constants import DEFAULT_TIMEOUT, PROWLARR_API_PATH
from arr_mcp.services.base import BaseArrClient, build_cloudflare_access_auth


class ProwlarrClient(BaseArrClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT,
        cloudflare_access_client_id: str = "",
        cloudflare_access_client_secret: str = "",
    ) -> None:
        super().__init__(
            name="Prowlarr",
            base_url=base_url,
            api_key=api_key,
            api_path=PROWLARR_API_PATH,
            timeout=timeout,
            cloudflare_access_auth=build_cloudflare_access_auth(
                cloudflare_access_client_id,
                cloudflare_access_client_secret,
            ),
        )

    # ── indexers ──────────────────────────────────────────────────

    async def get_indexers(self) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/indexer")  # type: ignore[return-value]

    async def get_indexer(self, indexer_id: int) -> dict[str, Any]:
        return await self._get(f"{self.api_path}/indexer/{indexer_id}")  # type: ignore[return-value]

    async def add_indexer(self, **fields: Any) -> dict[str, Any]:
        return await self._post(f"{self.api_path}/indexer", json=fields)

    async def update_indexer(self, indexer_id: int, **fields: Any) -> dict[str, Any]:
        """Merge ``fields`` into the stored indexer and PUT the full resource.

        Prowlarr's ``PUT /api/v1/indexer/{id}`` validates the whole indexer
        resource, so a partial payload is rejected with 400.  Fetch the
        existing indexer first (same pattern as the other *arr update methods).
        """
        indexer = await self.get_indexer(indexer_id)
        indexer.update(fields)
        return await self._put(f"{self.api_path}/indexer/{indexer_id}", json=indexer)

    async def delete_indexer(self, indexer_id: int) -> dict[str, Any]:
        return await self._delete(f"{self.api_path}/indexer/{indexer_id}")  # type: ignore[return-value]

    async def test_indexer(self, indexer_id: int) -> dict[str, Any]:
        indexer = await self.get_indexer(indexer_id)
        return await self._post(f"{self.api_path}/indexer/test", json=indexer)

    async def test_all_indexers(self) -> dict[str, Any]:
        """Test every enabled indexer.

        Prowlarr answers ``POST /api/v1/indexer/testall`` with HTTP **400**
        whenever at least one indexer fails validation, while still returning
        the per-indexer result array in the body.  Surface that body instead of
        treating the response as a hard failure.
        """
        try:
            return await self._post(f"{self.api_path}/indexer/testall")  # type: ignore[return-value]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                try:
                    return exc.response.json()  # type: ignore[return-value]
                except ValueError:
                    pass
            raise

    async def get_indexer_schema(self) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/indexer/schema")  # type: ignore[return-value]

    # ── unified search ────────────────────────────────────────────

    async def search(
        self,
        query: str,
        categories: list[int] | None = None,
        indexer_ids: list[int] | None = None,
        search_type: str = "search",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "query": query,
            "type": search_type,
            "limit": limit,
            "offset": offset,
        }
        if categories:
            params["categories"] = categories
        if indexer_ids:
            params["indexerIds"] = indexer_ids
        return await self._get(f"{self.api_path}/search", **params)  # type: ignore[return-value]

    # ── applications (synced arr apps) ────────────────────────────

    async def get_applications(self) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/applications")  # type: ignore[return-value]

    async def get_application(self, app_id: int) -> dict[str, Any]:
        return await self._get(f"{self.api_path}/applications/{app_id}")  # type: ignore[return-value]

    async def sync_application(self, app_id: int) -> dict[str, Any]:
        """Push indexers to the connected applications.

        Prowlarr exposes no per-application sync route (``/applications/{id}/sync``
        returns 405).  Syncing is performed by the ``ApplicationIndexerSync``
        command, which pushes indexers to every enabled application — including
        ``app_id``.
        """
        return await self.trigger_command("ApplicationIndexerSync", forceSync=True)

    async def sync_all_applications(self) -> dict[str, Any]:
        """Push indexers to every enabled application via the sync command."""
        return await self.trigger_command("ApplicationIndexerSync", forceSync=True)

    async def test_application(self, app_id: int) -> dict[str, Any]:
        app = await self.get_application(app_id)
        return await self._post(f"{self.api_path}/applications/test", json=app)

    # ── history ───────────────────────────────────────────────────

    async def get_history_since(self, date: str) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/history/since", date=date)  # type: ignore[return-value]

    async def get_indexer_history(self, indexer_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return await self._get(  # type: ignore[return-value]
            f"{self.api_path}/history/indexer",
            indexerId=indexer_id,
            limit=limit,
        )

    # ── notifications ─────────────────────────────────────────────

    async def get_notifications(self) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/notification")  # type: ignore[return-value]

    # ── download clients ──────────────────────────────────────────

    async def get_download_clients(self) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/downloadclient")  # type: ignore[return-value]

    # ── stats ─────────────────────────────────────────────────────

    async def get_indexer_stats(self) -> dict[str, Any]:
        return await self._get(f"{self.api_path}/indexerstats")  # type: ignore[return-value]

    # ── disk / queue / wanted (not available in Prowlarr API) ────────

    async def get_diskspace(self) -> list[dict[str, Any]]:
        """Prowlarr does not expose disk space endpoints; returns empty list."""
        return []

    async def get_queue(
        self,
        page: int = 1,
        page_size: int = 20,
        include_unknown: bool = True,
    ) -> dict[str, Any]:
        """Prowlarr does not expose a queue endpoint; returns empty queue structure."""
        return {"records": [], "totalRecords": 0, "page": page}

    async def get_wanted_missing(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_key: str = "title",
        sort_direction: str = "ascending",
        monitored: bool = True,
    ) -> dict[str, Any]:
        """Prowlarr does not expose wanted/missing endpoints; returns empty structure."""
        return {"records": [], "totalRecords": 0, "page": page}

    # ── notifications schema ──────────────────────────────────────

    async def get_notification_schema(self) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/notification/schema")  # type: ignore[return-value]
