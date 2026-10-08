from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _normalize_verdict(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r"[\s\-]+", "_", value.strip().strip(".:").strip().lower())
    return value


def _claim_text(item: object) -> str:
    if isinstance(item, dict):
        inner = next(iter(item.values())) if len(item) == 1 else None
        if not isinstance(inner, str):
            raise ValueError("a claim object must hold exactly one string value")
        item = inner
    if not isinstance(item, str):
        raise ValueError("each claim must be a string")
    return item.strip()


class ExtractOut(BaseModel):
    claims: list[str]

    @field_validator("claims", mode="before")
    @classmethod
    def _clean(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [text for text in (_claim_text(c) for c in value if c is not None) if text]


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
        if isinstance(value, str | int):
            return [str(value)]
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
