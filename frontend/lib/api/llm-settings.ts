import { apiGet, apiPost, apiPut } from "./client";
import type { LlmSettings, LlmSettingsUpdate } from "./types";

export function getLlmSettings(): Promise<LlmSettings> {
  return apiGet<LlmSettings>("/api/v1/settings/llm");
}

export function updateLlmSettings(body: LlmSettingsUpdate): Promise<LlmSettings> {
  return apiPut<LlmSettings>("/api/v1/settings/llm", body);
}

export function resetLlmSettings(): Promise<LlmSettings> {
  return apiPost<LlmSettings>("/api/v1/settings/llm/reset", {});
}
