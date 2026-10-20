"""Public SII projection: no roles or third-party address fields."""

from pydantic import BaseModel, Field


class SiiCandidateOut(BaseModel):
    id: str
    label: str


class SiiClosingOpinionOut(BaseModel):
    status: str
    confidence_label: str | None = None
    value_uf: float | None = None
    p25_uf: float | None = None
    p75_uf: float | None = None
    comparable_count: int = 0
    closing_dates: list[str] = Field(default_factory=list)
    date_min: str | None = None
    date_max: str | None = None
    area_m2: float | None = None
    area_basis: str | None = None
    message: str
    scope_message: str | None = None
    reason_code: str | None = None
    candidates: list[SiiCandidateOut] = Field(default_factory=list)
    candidate_count: int = 0
