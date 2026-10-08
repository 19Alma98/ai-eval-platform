from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _normalize_verdict(value: object) -> object:
    if isinstance(value, str):
        return value.strip().lower().replace(" ", "_").replace("-", "_")
    return value


class ExtractOut(BaseModel):
    claims: list[str]

    @field_validator("claims", mode="before")
    @classmethod
    def _clean(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(c).strip() for c in value if c is not None and str(c).strip()]


class SupportVerdict(BaseModel):
    reasoning: str | None = None
    verdict: Literal["supported", "contradicted", "not_supported"]
    doc_ids: list[str] = Field(default_factory=list)
    quote: str | None = None

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _normalize_verdict(value)

    @field_validator("doc_ids", mode="before")
    @classmethod
    def _doc_ids(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v is not None]
        return value


class SupportVerifyOut(BaseModel):
    verdicts: list[SupportVerdict]


class CoverageVerdict(BaseModel):
    reasoning: str | None = None
    verdict: Literal["covered", "contradicted", "missing"]

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _normalize_verdict(value)


class CoverageVerifyOut(BaseModel):
    verdicts: list[CoverageVerdict]


class RubricOut(BaseModel):
    reasoning: str | None = None
    level: int = Field(ge=1, le=5)
