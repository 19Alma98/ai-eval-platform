import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type { AlertEvaluation, AlertEvent, AlertRule, AlertRuleInput } from "./types";

export function listAlertRules(projectId: string) {
  return apiGet<AlertRule[]>(`/api/v1/projects/${projectId}/alert-rules`);
}

export function createAlertRule(projectId: string, body: AlertRuleInput) {
  return apiPost<AlertRule>(`/api/v1/projects/${projectId}/alert-rules`, body);
}

export function updateAlertRule(ruleId: string, body: Partial<AlertRuleInput>) {
  return apiPatch<AlertRule>(`/api/v1/alert-rules/${ruleId}`, body);
}

export function deleteAlertRule(ruleId: string) {
  return apiDelete(`/api/v1/alert-rules/${ruleId}`);
}

export function testAlertRule(ruleId: string) {
  return apiPost<AlertEvent>(`/api/v1/alert-rules/${ruleId}/test`, {});
}

export function evaluateAlertRules(projectId: string) {
  return apiPost<AlertEvaluation[]>(`/api/v1/projects/${projectId}/alert-rules/evaluate`, {});
}

export function listAlertEvents(projectId: string, limit = 50) {
  return apiGet<AlertEvent[]>(`/api/v1/projects/${projectId}/alert-events?limit=${limit}`);
}
