from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from opengrade_server.api.deps import get_evaluate_alert_rules, get_manage_alert_rules
from opengrade_server.api.schemas import (
    AlertEvaluationResponse,
    AlertEventResponse,
    AlertRuleResponse,
    CreateAlertRuleRequest,
    UpdateAlertRuleRequest,
)
from opengrade_server.application.alerts import (
    AlertRuleFields,
    AlertRuleNotFoundError,
    EvaluateAlertRules,
    ManageAlertRules,
)
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.alert import AlertEvent, AlertRule, AlertRuleValidationError

router = APIRouter(tags=["alerts"])


def _rule_response(rule: AlertRule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=rule.id,
        project_id=rule.project_id,
        name=rule.name,
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        window_minutes=rule.window_minutes,
        min_samples=rule.min_samples,
        score_name=rule.score_name,
        score_source=rule.score_source,
        webhook_url=rule.webhook_url,
        webhook_format=rule.webhook_format,
        repeat_minutes=rule.repeat_minutes,
        enabled=rule.enabled,
        state=rule.state,
        last_value=rule.last_value,
        last_evaluated_at=rule.last_evaluated_at,
        last_notified_at=rule.last_notified_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        environment=rule.environment,
        version=rule.version,
    )


def _event_response(event: AlertEvent) -> AlertEventResponse:
    return AlertEventResponse(
        id=event.id,
        rule_id=event.rule_id,
        project_id=event.project_id,
        kind=event.kind,
        value=event.value,
        threshold=event.threshold,
        message=event.message,
        delivery_status=event.delivery_status,
        delivery_error=event.delivery_error,
        created_at=event.created_at,
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _invalid(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/api/v1/projects/{project_id}/alert-rules",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_rule(
    project_id: uuid.UUID,
    body: CreateAlertRuleRequest,
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> AlertRuleResponse:
    try:
        rule = await use_case.create(project_id, AlertRuleFields(**body.model_dump()))
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except AlertRuleValidationError as exc:
        raise _invalid(exc) from exc
    return _rule_response(rule)


@router.get("/api/v1/projects/{project_id}/alert-rules", response_model=list[AlertRuleResponse])
async def list_alert_rules(
    project_id: uuid.UUID,
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> list[AlertRuleResponse]:
    try:
        rules = await use_case.list_rules(project_id)
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return [_rule_response(rule) for rule in rules]


@router.post(
    "/api/v1/projects/{project_id}/alert-rules/evaluate",
    response_model=list[AlertEvaluationResponse],
)
async def evaluate_alert_rules(
    project_id: uuid.UUID,
    use_case: EvaluateAlertRules = Depends(get_evaluate_alert_rules),
) -> list[AlertEvaluationResponse]:
    """Evaluate the project's enabled rules now (the server also does it periodically)."""
    results = await use_case.execute(project_id=project_id)
    return [
        AlertEvaluationResponse(
            rule=_rule_response(r.rule),
            value=r.value,
            samples=r.samples,
            event=_event_response(r.event) if r.event else None,
        )
        for r in results
    ]


@router.get("/api/v1/projects/{project_id}/alert-events", response_model=list[AlertEventResponse])
async def list_alert_events(
    project_id: uuid.UUID,
    rule_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> list[AlertEventResponse]:
    try:
        events = await use_case.events(project_id, rule_id=rule_id, limit=limit)
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return [_event_response(e) for e in events]


@router.get("/api/v1/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: uuid.UUID,
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> AlertRuleResponse:
    try:
        return _rule_response(await use_case.get(rule_id))
    except AlertRuleNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/api/v1/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: uuid.UUID,
    body: UpdateAlertRuleRequest,
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> AlertRuleResponse:
    values = body.model_dump(exclude_unset=True)
    cleared = frozenset(k for k, v in values.items() if v is None)
    fields = AlertRuleFields(
        **{k: v for k, v in values.items() if v is not None},
        clear=cleared,
    )
    try:
        rule = await use_case.update(rule_id, fields)
    except AlertRuleNotFoundError as exc:
        raise _not_found(exc) from exc
    except AlertRuleValidationError as exc:
        raise _invalid(exc) from exc
    return _rule_response(rule)


@router.delete("/api/v1/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: uuid.UUID,
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> Response:
    try:
        await use_case.delete(rule_id)
    except AlertRuleNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/v1/alert-rules/{rule_id}/test", response_model=AlertEventResponse)
async def test_alert_rule(
    rule_id: uuid.UUID,
    use_case: ManageAlertRules = Depends(get_manage_alert_rules),
) -> AlertEventResponse:
    """Send a test notification to the rule's webhook and log it."""
    try:
        return _event_response(await use_case.send_test(rule_id))
    except AlertRuleNotFoundError as exc:
        raise _not_found(exc) from exc
