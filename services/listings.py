"""Listing read use cases."""
from __future__ import annotations

from collections.abc import Sequence

from core.entities.listing import Listing
from core.exceptions import ListingNotFoundError
from core.ports.listing_repo import ListingRepository


class ListingService:
    def __init__(self, listing_repo: ListingRepository) -> None:
        self._listing_repo = listing_repo

    async def list_listings(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        comuna: str | None = None,
        status: str | None = None,
    ) -> Sequence[Listing]:
        return await self._listing_repo.list(
            limit=limit,
            offset=offset,
            comuna=comuna,
            status=status,
        )

    async def get_listing(self, listing_id: int) -> Listing:
        listing = await self._listing_repo.find_by_id(listing_id)
        if listing is None:
            raise ListingNotFoundError(f"Listing id={listing_id} no existe")
        return listing
