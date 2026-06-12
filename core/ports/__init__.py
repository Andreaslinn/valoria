"""Puertos (interfaces abstractas) que el dominio usa para hablar con el mundo externo.

El dominio depende de estas abstracciones, no de implementaciones concretas.
Las implementaciones viven en infrastructure/.
"""
from core.ports.listing_repo import ListingRepository
from core.ports.price_history_repo import PriceHistoryRepository
from core.ports.property_repo import PropertyRepository
from core.ports.uf_service import UFService
from core.ports.user_repo import UserRepository

__all__ = [
    "ListingRepository",
    "PriceHistoryRepository",
    "PropertyRepository",
    "UFService",
    "UserRepository",
]
