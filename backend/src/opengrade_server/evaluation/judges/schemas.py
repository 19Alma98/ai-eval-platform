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


class RelevanceVerdict(BaseModel):
    reasoning: str | None = None
    verdict: Literal["relevant", "not_relevant"]

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: object) -> object:
        return _normalize_verdict(value)


class RelevanceVerifyOut(BaseModel):
    verdicts: list[RelevanceVerdict]


class RubricOut(BaseModel):
    reasoning: str | None = None
    level: int = Field(ge=1, le=5)


def _optional_bool(value: object) -> object:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "null", "none", "n/a"):
            return None
        if text in ("true", "yes"):
            return True
        if text in ("false", "no"):
            return False
    return value


class RefusalOut(BaseModel):
    reasoning: str | None = None
    answer_refused: bool
    reference_refused: bool | None = None
    answerable_from_documents: bool | None = None

    @field_validator(
        "answer_refused", "reference_refused", "answerable_from_documents", mode="before"
    )
    @classmethod
    def _bool(cls, value: object) -> object:
        return _optional_bool(value)


class SafetyClassifyOut(BaseModel):
    """Shared reply of the pii / toxicity / prompt_injection classifiers.

    Categories are free strings here: the judge maps unknown ones to "other".
    """

    reasoning: str | None = None
    flagged: bool
    categories: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("flagged", mode="before")
    @classmethod
    def _flagged(cls, value: object) -> object:
        return _optional_bool(value)

    @field_validator("categories", "evidence", mode="before")
    @classmethod
    def _strings(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            return [str(v).strip() for v in value if v is not None and str(v).strip()]
        return value
