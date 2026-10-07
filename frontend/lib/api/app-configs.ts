import { apiDelete, apiGet, apiPut } from "./client";
import type { AppConfig, AppConfigAlias } from "./types";

export function listAppConfigs(
  projectId: string,
  opts?: { name?: string; latest?: boolean },
) {
  const params = new URLSearchParams();
  if (opts?.name) params.set("name", opts.name);
  if (opts?.latest) params.set("latest", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiGet<AppConfig[]>(
    `/api/v1/projects/${projectId}/app-configs${qs}`,
  );
}

export function listAppConfigVersions(projectId: string, name: string) {
  return apiGet<AppConfig[]>(
    `/api/v1/projects/${projectId}/app-configs/by-name/${encodeURIComponent(name)}/versions`,
  );
}

export function listAliases(projectId: string) {
  return apiGet<AppConfigAlias[]>(
    `/api/v1/projects/${projectId}/app-config-aliases`,
  );
}

export function setAlias(
  projectId: string,
  alias: string,
  appConfigId: string,
) {
  return apiPut<AppConfigAlias>(
    `/api/v1/projects/${projectId}/app-config-aliases/${encodeURIComponent(alias)}`,
    { app_config_id: appConfigId },
  );
}

export function deleteAlias(projectId: string, alias: string) {
  return apiDelete(
    `/api/v1/projects/${projectId}/app-config-aliases/${encodeURIComponent(alias)}`,
  );
}
