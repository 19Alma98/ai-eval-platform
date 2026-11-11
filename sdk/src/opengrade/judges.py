"""Custom LLM judges defined in code, run by the OpenGrade server.

```python
tone = opengrade.LlmJudge(
    "tone",
    criteria="The answer is polite and professional, with no slang.",
    scale="binary",
)
og.evaluate(dataset="gold-v1", task=answer, metrics=["groundedness", tone])
```

The judge is stored on the server as a project evaluator (``kind: custom_judge``), so
its scores show up in the UI, in compare and in the release gate like built-in
metrics. ``live=True`` also applies it to production traffic (``og.init_tracing(live=True)``).
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from opengrade.client import Client
    from opengrade.models import EvaluatorPreviewResponse, EvaluatorResponse

CUSTOM_JUDGE_KIND = "custom_judge"
_FIELDS = ("input", "output", "expected", "documents", "metadata")


@dataclass(frozen=True)
class LlmJudge:
    """A judge described in plain language.

    - ``criteria``: what a good answer looks like (the judge's instructions).
    - ``scale``: ``"1-5"`` (score 0, 0.25, ... 1) or ``"binary"`` (pass = 1, fail = 0).
    - ``levels``: optional descriptions per level for ``"1-5"`` (``{5: "...", 1: "..."}``).
    - ``fields``: what the judge sees, from ``input``, ``output``, ``expected``,
      ``documents``, ``metadata``. ``output`` is required. A judge that reads
      ``expected`` only runs on test sets.
    - ``examples``: up to 5 graded examples (``{"output": ..., "level": 2}`` or
      ``{"output": ..., "verdict": "fail"}``, optional ``input``/``expected``/``reasoning``).
    - ``threshold``: pass mark (0..1). Default 0.5.
    - ``live``: also score production traffic.
    - ``model`` / ``temperature``: judge model override (default: server ``LLM_MODEL``).
    """

    name: str
    criteria: str
    scale: Literal["1-5", "binary"] = "1-5"
    levels: Mapping[int, str] | None = None
    fields: Sequence[str] = ("input", "output")
    examples: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    threshold: float | None = 0.5
    live: bool = False
    model: str | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("LlmJudge needs a name")
        if not self.criteria or not self.criteria.strip():
            raise ValueError("LlmJudge needs criteria")
        if self.scale not in ("1-5", "binary"):
            raise ValueError("LlmJudge scale must be '1-5' or 'binary'")
        unknown = sorted(set(self.fields) - set(_FIELDS))
        if unknown:
            raise ValueError(f"LlmJudge: unknown fields {unknown}; allowed: {list(_FIELDS)}")
        if "output" not in self.fields:
            raise ValueError("LlmJudge fields must include 'output'")
        if self.live and "expected" in self.fields:
            raise ValueError("a live LlmJudge cannot read 'expected' (no reference in production)")
        if self.threshold is not None and not 0.0 <= self.threshold <= 1.0:
            raise ValueError("LlmJudge threshold must be between 0 and 1")

    def config(self) -> dict[str, Any]:
        """The evaluator config sent to the server."""
        config: dict[str, Any] = {
            "kind": CUSTOM_JUDGE_KIND,
            "criteria": self.criteria.strip(),
            "scale": self.scale,
            "fields": [f for f in _FIELDS if f in self.fields],
        }
        if self.levels:
            config["levels"] = {str(k): v for k, v in sorted(self.levels.items())}
        if self.examples:
            config["examples"] = [dict(e) for e in self.examples]
        if self.live:
            config["live"] = True
            if self.threshold is not None:
                config["threshold"] = self.threshold
        if self.model:
            config["model"] = self.model
        if self.temperature is not None:
            config["temperature"] = self.temperature
        return config

    def register(
        self, client: Client | None = None, project_id: str | None = None
    ) -> EvaluatorResponse:
        """Create the evaluator on the server, or reuse the one with the same config.

        A changed config creates a new version (scores from different criteria are not
        compared as if they were the same metric). The latest version of a ``live`` judge
        is the one applied to production traffic.
        """
        if client is None:
            from opengrade._opengrade import default_instance

            client = default_instance().client
        project_id = client._project(project_id)
        name = self.name.strip()
        config = self.config()
        same_name = [e for e in client.evaluators.list(project_id) if e.name == name]
        for existing in same_name:
            if existing.config == config:
                return existing
        version = max((e.version for e in same_name), default=0) + 1
        return client.evaluators.create(
            project_id, name=name, type="llm_judge", config=config, version=version
        )

    def preview(
        self,
        *,
        output: Any,
        input: Any = None,
        expected_output: Any = None,
        documents: builtins.list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        client: Client | None = None,
        project_id: str | None = None,
    ) -> EvaluatorPreviewResponse:
        """Grade one sample now (nothing is stored). Returns score, explanation, prompt."""
        if client is None:
            from opengrade._opengrade import default_instance

            client = default_instance().client
        return client.evaluators.preview(
            client._project(project_id),
            config=self.config(),
            input=input,
            output=output,
            expected_output=expected_output,
            documents=documents,
            metadata=metadata,
        )
