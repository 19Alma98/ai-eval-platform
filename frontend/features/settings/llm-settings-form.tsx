"use client";

import { useState, type ReactNode, type SubmitEvent } from "react";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatErrorForUi } from "@/lib/api/client";
import type { LlmSettingSource, LlmSettings, LlmSettingsUpdate } from "@/lib/api/types";
import { useLlmSettings, useResetLlmSettings, useUpdateLlmSettings } from "./use-llm-settings";

function SourceHint({ source }: { source: LlmSettingSource | undefined }) {
  if (!source) return null;
  return (
    <Badge variant="outline" className="font-normal text-muted-foreground">
      {source === "db" ? "UI override" : "from env"}
    </Badge>
  );
}

function Field({
  id,
  label,
  source,
  children,
  hint,
}: {
  id: string;
  label: string;
  source?: LlmSettingSource;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <SourceHint source={source} />
      </div>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function formStateFrom(settings: LlmSettings) {
  return {
    model: settings.model,
    api_base: settings.api_base ?? "",
    api_key: "",
    clearApiKey: false,
    timeout_seconds: String(settings.timeout_seconds),
    max_retries: String(settings.max_retries),
    max_concurrency: String(settings.max_concurrency),
    temperature: String(settings.temperature),
    seed: settings.seed === null ? "" : String(settings.seed),
  };
}

export function LlmSettingsForm() {
  const query = useLlmSettings(true);

  if (query.isLoading) return <LoadingBlock className="min-h-[160px]" />;
  if (query.isError) {
    return (
      <ErrorState
        title="Could not load LLM settings"
        message={formatErrorForUi(query.error)}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!query.data) return <LoadingBlock className="min-h-[160px]" />;

  return <LlmSettingsFormLoaded settings={query.data} />;
}

function LlmSettingsFormLoaded({ settings }: { settings: LlmSettings }) {
  const update = useUpdateLlmSettings();
  const reset = useResetLlmSettings();
  const [advanced, setAdvanced] = useState(false);
  const [form, setForm] = useState(() => formStateFrom(settings));

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    const body: LlmSettingsUpdate = {
      model: form.model.trim(),
      api_base: form.api_base.trim() ? form.api_base.trim() : null,
      timeout_seconds: Number(form.timeout_seconds),
      max_retries: Number(form.max_retries),
      max_concurrency: Number(form.max_concurrency),
      temperature: Number(form.temperature),
      seed: form.seed.trim() === "" ? null : Number(form.seed),
    };
    if (form.clearApiKey) {
      body.api_key = null;
    } else if (form.api_key.trim()) {
      body.api_key = form.api_key.trim();
    }
    update.mutate(body, {
      onSuccess: (data) => setForm(formStateFrom(data)),
    });
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold tracking-tight text-foreground">LLM judges</h2>
          <p className="text-xs text-muted-foreground">
            Model and knobs are stored in the database. The API key is written only to the
            server <code className="text-xs">.env</code>, never to the DB.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={reset.isPending || update.isPending}
          onClick={() =>
            reset.mutate(undefined, {
              onSuccess: (data) => setForm(formStateFrom(data)),
            })
          }
        >
          Reset to environment
        </Button>
      </div>

      <form
        onSubmit={handleSubmit}
        aria-label="LLM judge settings"
        className="flex flex-col gap-4 border-b border-border py-4"
      >
        <Field id="llm-model" label="Model" source={settings.sources.model}>
          <Input
            id="llm-model"
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            placeholder="gemini/gemini-3.8-flash"
            required
          />
        </Field>

        <Field
          id="llm-api-base"
          label="API base"
          source={settings.sources.api_base}
          hint="Optional. e.g. http://localhost:11434 for Ollama."
        >
          <Input
            id="llm-api-base"
            value={form.api_base}
            onChange={(e) => setForm({ ...form, api_base: e.target.value })}
            placeholder="(provider default)"
          />
        </Field>

        <Field
          id="llm-api-key"
          label="API key"
          hint={
            settings.api_key_set
              ? "Key is set in .env. Leave blank to keep it, or clear it."
              : "Not set. Paste a key to write LLM_API_KEY into the server .env."
          }
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              id="llm-api-key"
              type="password"
              autoComplete="off"
              value={form.api_key}
              disabled={form.clearApiKey}
              onChange={(e) => setForm({ ...form, api_key: e.target.value, clearApiKey: false })}
              placeholder={settings.api_key_set ? "•••••••• (unchanged)" : "LLM_API_KEY"}
              className="sm:flex-1"
            />
            {settings.api_key_set ? (
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  checked={form.clearApiKey}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      clearApiKey: e.target.checked,
                      api_key: e.target.checked ? "" : form.api_key,
                    })
                  }
                />
                Clear from .env
              </label>
            ) : null}
          </div>
        </Field>

        <div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="px-0"
            onClick={() => setAdvanced((v) => !v)}
          >
            {advanced ? "Hide advanced" : "Show advanced"}
          </Button>
        </div>

        {advanced ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              id="llm-timeout"
              label="Timeout (seconds)"
              source={settings.sources.timeout_seconds}
            >
              <Input
                id="llm-timeout"
                type="number"
                min={0.1}
                step="any"
                value={form.timeout_seconds}
                onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })}
                required
              />
            </Field>
            <Field
              id="llm-retries"
              label="Max retries"
              source={settings.sources.max_retries}
            >
              <Input
                id="llm-retries"
                type="number"
                min={0}
                step={1}
                value={form.max_retries}
                onChange={(e) => setForm({ ...form, max_retries: e.target.value })}
                required
              />
            </Field>
            <Field
              id="llm-concurrency"
              label="Max concurrency"
              source={settings.sources.max_concurrency}
            >
              <Input
                id="llm-concurrency"
                type="number"
                min={1}
                step={1}
                value={form.max_concurrency}
                onChange={(e) => setForm({ ...form, max_concurrency: e.target.value })}
                required
              />
            </Field>
            <Field
              id="llm-temperature"
              label="Temperature"
              source={settings.sources.temperature}
            >
              <Input
                id="llm-temperature"
                type="number"
                min={0}
                max={2}
                step="any"
                value={form.temperature}
                onChange={(e) => setForm({ ...form, temperature: e.target.value })}
                required
              />
            </Field>
            <Field
              id="llm-seed"
              label="Seed"
              source={settings.sources.seed}
              hint="Empty uses the environment default (or none)."
            >
              <Input
                id="llm-seed"
                type="number"
                step={1}
                value={form.seed}
                onChange={(e) => setForm({ ...form, seed: e.target.value })}
                placeholder="(env default)"
              />
            </Field>
          </div>
        ) : null}

        <div className="flex justify-end">
          <Button type="submit" size="sm" disabled={update.isPending || reset.isPending}>
            {update.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </section>
  );
}
