"""Server-side alert rules on production monitoring metrics, and their event log."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

AlertMetric = Literal[
    "error_rate",
    "latency_p50_ms",
    "latency_p90_ms",
    "latency_p99_ms",
    "traffic",
    "cost_usd",
    "total_tokens",
    "needs_review",
    "score_mean",
    "score_fail_rate",
]
AlertOperator = Literal["gt", "lt", "abs"]
# threshold: the metric itself vs ``threshold``.
# change: relative change of the metric vs the previous ``baseline_minutes``
#   ((current - baseline) / |baseline|; 0.3 = +30%) — drift.
# anomaly: z-score of the metric vs the same-size windows of the previous
#   ``baseline_minutes`` ((current - mean) / std) — spikes and drops.
AlertCondition = Literal["threshold", "change", "anomaly"]
AlertState = Literal["ok", "firing", "no_data"]
AlertEventKind = Literal["firing", "resolved", "repeat", "test"]
DeliveryStatus = Literal["sent", "failed", "skipped"]
WebhookFormat = Literal["json", "slack"]

ALERT_METRICS: frozenset[str] = frozenset(
    {
        "error_rate",
        "latency_p50_ms",
        "latency_p90_ms",
        "latency_p99_ms",
        "traffic",
        "cost_usd",
        "total_tokens",
        "needs_review",
        "score_mean",
        "score_fail_rate",
    }
)
SCORE_METRICS = frozenset({"score_mean", "score_fail_rate"})
# Metrics whose value is a rate or a percentile over traces: too few samples is no data.
SAMPLED_METRICS = frozenset(
    {"error_rate", "latency_p50_ms", "latency_p90_ms", "latency_p99_ms", *SCORE_METRICS}
)

ALERT_CONDITIONS: frozenset[str] = frozenset({"threshold", "change", "anomaly"})
NAME_MAX_LENGTH = 200
URL_MAX_LENGTH = 2000
MIN_WINDOW_MINUTES = 5
MAX_WINDOW_MINUTES = 7 * 24 * 60
DEFAULT_MIN_SAMPLES = 10
MAX_BASELINE_MINUTES = 30 * 24 * 60
# Anomaly baselines: enough past windows for a mean / std, few enough to query.
MIN_ANOMALY_BUCKETS = 3
MAX_ANOMALY_BUCKETS = 48
DEFAULT_ANOMALY_BUCKETS = 24


class AlertRuleValidationError(ValueError):
    pass


def validate_webhook_url(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    cleaned = url.strip()
    if len(cleaned) > URL_MAX_LENGTH:
        raise AlertRuleValidationError(f"webhook_url must be at most {URL_MAX_LENGTH} characters")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AlertRuleValidationError("webhook_url must be an http(s) URL")
    return cleaned


@dataclass(frozen=True, slots=True)
class AlertRule:
    """``metric`` over the last ``window_minutes`` compared with ``threshold``.

    ``score_*`` metrics read one production score (``score_name``; ``score_source`` narrows
    it to one source such as ``judge`` or ``sdk``). ``repeat_minutes`` re-notifies while
    the rule keeps firing; without it only state changes notify.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    metric: str
    operator: str
    threshold: float
    window_minutes: int
    min_samples: int
    score_name: str | None
    score_source: str | None
    webhook_url: str | None
    webhook_format: str
    repeat_minutes: int | None
    enabled: bool
    state: str
    last_value: float | None
    last_evaluated_at: datetime | None
    last_notified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Only traces of this deployment environment / release count (None = all).
    environment: str | None = None
    version: str | None = None
    condition: str = "threshold"
    # Comparison period before the current window (change / anomaly only).
    baseline_minutes: int | None = None
    # Last raw metric value and its baseline (mean of the past windows) — for change /
    # anomaly rules ``last_value`` holds the relative change / z-score instead.
    last_observed: float | None = None
    last_baseline: float | None = None

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        *,
        name: str,
        metric: str,
        operator: str,
        threshold: float,
        window_minutes: int = 60,
        min_samples: int | None = None,
        score_name: str | None = None,
        score_source: str | None = None,
        webhook_url: str | None = None,
        webhook_format: str = "json",
        repeat_minutes: int | None = None,
        enabled: bool = True,
        environment: str | None = None,
        version: str | None = None,
        condition: str = "threshold",
        baseline_minutes: int | None = None,
    ) -> AlertRule:
        now = datetime.now(UTC)
        rule = cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            metric=metric,
            operator=operator,
            threshold=threshold,
            window_minutes=window_minutes,
            min_samples=(
                min_samples
                if min_samples is not None
                else (DEFAULT_MIN_SAMPLES if metric in SAMPLED_METRICS else 0)
            ),
            score_name=score_name,
            score_source=score_source,
            webhook_url=webhook_url,
            webhook_format=webhook_format,
            repeat_minutes=repeat_minutes,
            enabled=enabled,
            state="no_data",
            last_value=None,
            last_evaluated_at=None,
            last_notified_at=None,
            created_at=now,
            updated_at=now,
            environment=environment,
            version=version,
            condition=condition,
            baseline_minutes=baseline_minutes,
        )
        return rule.validated()

    def validated(self) -> AlertRule:
        name = self.name.strip()
        if not name or len(name) > NAME_MAX_LENGTH:
            raise AlertRuleValidationError(f"name must be 1-{NAME_MAX_LENGTH} characters")
        if self.metric not in ALERT_METRICS:
            raise AlertRuleValidationError(
                f"metric must be one of {sorted(ALERT_METRICS)}, got {self.metric!r}"
            )
        if self.condition not in ALERT_CONDITIONS:
            raise AlertRuleValidationError(
                f"condition must be one of {sorted(ALERT_CONDITIONS)}, got {self.condition!r}"
            )
        if self.operator not in {"gt", "lt", "abs"}:
            raise AlertRuleValidationError("operator must be 'gt', 'lt' or 'abs'")
        if self.operator == "abs" and self.condition == "threshold":
            raise AlertRuleValidationError(
                "operator 'abs' (either direction) only applies to change / anomaly rules"
            )
        if self.operator == "abs" and self.threshold < 0:
            raise AlertRuleValidationError("operator 'abs' needs a threshold >= 0")
        baseline_minutes = self._validated_baseline()
        if not math.isfinite(self.threshold):
            raise AlertRuleValidationError("threshold must be finite")
        if not MIN_WINDOW_MINUTES <= self.window_minutes <= MAX_WINDOW_MINUTES:
            raise AlertRuleValidationError(
                f"window_minutes must be between {MIN_WINDOW_MINUTES} and {MAX_WINDOW_MINUTES}"
            )
        if self.min_samples < 0:
            raise AlertRuleValidationError("min_samples must be >= 0")
        score_name = (self.score_name or "").strip() or None
        score_source = (self.score_source or "").strip() or None
        if self.metric in SCORE_METRICS and score_name is None:
            raise AlertRuleValidationError(f"{self.metric} needs score_name")
        if self.metric not in SCORE_METRICS and (score_name or score_source):
            raise AlertRuleValidationError("score_name / score_source only apply to score_*")
        if self.webhook_format not in {"json", "slack"}:
            raise AlertRuleValidationError("webhook_format must be 'json' or 'slack'")
        if self.repeat_minutes is not None and self.repeat_minutes < MIN_WINDOW_MINUTES:
            raise AlertRuleValidationError(f"repeat_minutes must be >= {MIN_WINDOW_MINUTES}")
        environment = (self.environment or "").strip() or None
        version = (self.version or "").strip() or None
        for label, value in (("environment", environment), ("version", version)):
            if value is not None and len(value) > NAME_MAX_LENGTH:
                raise AlertRuleValidationError(f"{label} must be at most {NAME_MAX_LENGTH} chars")
        return replace(
            self,
            name=name,
            score_name=score_name,
            score_source=score_source,
            webhook_url=validate_webhook_url(self.webhook_url),
            environment=environment,
            version=version,
            baseline_minutes=baseline_minutes,
        )

    def _validated_baseline(self) -> int | None:
        if self.condition == "threshold":
            if self.baseline_minutes is not None:
                raise AlertRuleValidationError(
                    "baseline_minutes only applies to change / anomaly rules"
                )
            return None
        if self.metric == "needs_review":
            raise AlertRuleValidationError(
                "needs_review is a backlog count: use a threshold rule for it"
            )
        if self.baseline_minutes is None:
            buckets = 1 if self.condition == "change" else DEFAULT_ANOMALY_BUCKETS
            return min(self.window_minutes * buckets, MAX_BASELINE_MINUTES)
        if not self.window_minutes <= self.baseline_minutes <= MAX_BASELINE_MINUTES:
            raise AlertRuleValidationError(
                f"baseline_minutes must be between window_minutes ({self.window_minutes}) "
                f"and {MAX_BASELINE_MINUTES}"
            )
        if self.condition == "anomaly":
            buckets = self.baseline_minutes // self.window_minutes
            if not MIN_ANOMALY_BUCKETS <= buckets <= MAX_ANOMALY_BUCKETS:
                raise AlertRuleValidationError(
                    "anomaly rules compare the window with "
                    f"{MIN_ANOMALY_BUCKETS}-{MAX_ANOMALY_BUCKETS} past windows: "
                    f"baseline_minutes / window_minutes is {buckets}"
                )
        return self.baseline_minutes

    @property
    def anomaly_buckets(self) -> int:
        return (self.baseline_minutes or 0) // self.window_minutes

    def breached(self, value: float) -> bool:
        if self.operator == "abs":
            return abs(value) > self.threshold
        return value > self.threshold if self.operator == "gt" else value < self.threshold


@dataclass(frozen=True, slots=True)
class AlertEvent:
    id: uuid.UUID
    rule_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    value: float | None
    threshold: float
    message: str
    delivery_status: str
    delivery_error: str | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        rule: AlertRule,
        *,
        kind: str,
        value: float | None,
        message: str,
        delivery_status: str = "skipped",
        delivery_error: str | None = None,
    ) -> AlertEvent:
        return cls(
            id=uuid.uuid4(),
            rule_id=rule.id,
            project_id=rule.project_id,
            kind=kind,
            value=value,
            threshold=rule.threshold,
            message=message,
            delivery_status=delivery_status,
            delivery_error=delivery_error,
            created_at=datetime.now(UTC),
        )
