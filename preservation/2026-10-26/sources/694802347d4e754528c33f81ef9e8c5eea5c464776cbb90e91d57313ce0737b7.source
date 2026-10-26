"""Excepciones de dominio. Agnosticas a HTTP, DB u otra infraestructura.

Las capas externas las mapean a su propio formato de error, por ejemplo
ValidationError -> 422 en FastAPI.
"""


class AVMError(Exception):
    """Base de todas las excepciones del dominio."""


class ValidationError(AVMError):
    """El dato viola una regla de negocio."""


class InsufficientDataError(AVMError):
    """No hay suficientes comparables / dataset para una operacion confiable."""


class ListingNotFoundError(AVMError):
    pass


class PropertyNotFoundError(AVMError):
    pass


class DuplicateListingError(AVMError):
    """Se intento ingresar un listing cuyo fingerprint ya existe."""


class UnknownComunaError(ValidationError):
    """La comuna no esta en el catalogo canonico."""


class UFServiceError(AVMError):
    """Falla al obtener una tasa UF real; no debe usarse fallback inventado."""
