"use client";

import Link from "next/link";
import { useMemo, useState, type SubmitEvent } from "react";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { Button, buttonVariants } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import { useExperiments } from "@/features/experiments/use-experiments";
import { parsePolicyYaml } from "./parse-policy";
import { ReleaseResult } from "./release-result";
import { useReleaseCheck } from "./use-release";

export const DEFAULT_RELEASE_POLICY_YAML = `quality:
  min: 0.85
latency:
  p95_max_ms: 2000
regression:
  max_delta: -0.03
`;

type ReleaseCheckFormProps = {
  projectId: string;
  initialExperimentId?: string;
};

export function ReleaseCheckForm({
  projectId,
  initialExperimentId = "",
}: ReleaseCheckFormProps) {
  const experimentsQuery = useExperiments(projectId);
  const releaseCheck = useReleaseCheck(projectId);

  const [experimentId, setExperimentId] = useState(initialExperimentId);
  const [baselineExperimentId, setBaselineExperimentId] = useState("");
  const [policyYaml, setPolicyYaml] = useState(DEFAULT_RELEASE_POLICY_YAML);
  const [parseError, setParseError] = useState<string | null>(null);

  const selectedExperiment = useMemo(() => {
    const list = experimentsQuery.data ?? [];
    return list.find((e) => e.id === experimentId);
  }, [experimentsQuery.data, experimentId]);

  const experiments = experimentsQuery.data ?? [];

  function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setParseError(null);

    let policy: Record<string, unknown>;
    try {
      policy = parsePolicyYaml(policyYaml);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Invalid policy YAML";
      setParseError(message);
      releaseCheck.reset();
      return;
    }

    const baseline =
      baselineExperimentId.trim() ||
      selectedExperiment?.baseline_experiment_id ||
      null;

    releaseCheck.mutate({
      experiment_id: experimentId,
      baseline_experiment_id: baseline,
      policy,
    });
  }

  if (experimentsQuery.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (experimentsQuery.isError) {
    const err = experimentsQuery.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Could not load experiments"
        message={message}
        onRetry={() => void experimentsQuery.refetch()}
      />
    );
  }

  if (experiments.length === 0) {
    return (
      <EmptyState
        title="No experiments yet"
        description="Create and evaluate an experiment before running a release check."
        action={
          <Link
            href={withProjectQuery("/experiments", projectId)}
            className={cn(buttonVariants({ variant: "default", size: "sm" }))}
          >
            Go to Experiments
          </Link>
        }
      />
    );
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="release-experiment" className="text-sm font-medium">
            Experiment
          </label>
          <select
            id="release-experiment"
            required
            value={experimentId}
            onChange={(e) => setExperimentId(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">Select experiment…</option>
            {experiments.map((exp) => (
              <option key={exp.id} value={exp.id}>
                {exp.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="release-baseline" className="text-sm font-medium">
            Baseline experiment
          </label>
          <select
            id="release-baseline"
            value={baselineExperimentId}
            onChange={(e) => setBaselineExperimentId(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">
              {selectedExperiment?.baseline_experiment_id
                ? "Use experiment default baseline"
                : "None (required if policy includes regression)"}
            </option>
            {experiments.map((exp) => (
              <option key={exp.id} value={exp.id}>
                {exp.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="release-policy" className="text-sm font-medium">
            Policy (YAML)
          </label>
          <Textarea
            id="release-policy"
            value={policyYaml}
            onChange={(e) => {
              setPolicyYaml(e.target.value);
              if (parseError) setParseError(null);
            }}
            rows={12}
            className="font-mono text-xs"
            spellCheck={false}
          />
          {parseError ? (
            <p className="text-sm text-status-fail" role="alert">
              {parseError}
            </p>
          ) : null}
        </div>

        <Button type="submit" disabled={releaseCheck.isPending || !experimentId}>
          {releaseCheck.isPending ? "Running…" : "Run release check"}
        </Button>
      </form>

      {releaseCheck.isError ? (
        <ErrorState
          title="Release check request failed"
          message={
            releaseCheck.error instanceof ApiError
              ? `${releaseCheck.error.status}: ${releaseCheck.error.message}`
              : releaseCheck.error instanceof Error
                ? releaseCheck.error.message
                : "Unknown error"
          }
          onRetry={() => releaseCheck.reset()}
        />
      ) : null}

      {releaseCheck.data &&
      !parseError &&
      !releaseCheck.isPending &&
      !releaseCheck.isError ? (
        <ReleaseResult projectId={projectId} result={releaseCheck.data} />
      ) : null}
    </div>
  );
}
