import { toast } from "sonner";
import type { EvaluateResponse } from "@/lib/api/types";

export type EvaluateOutcomeKind = "success" | "with_errors";

export function classifyEvaluateResponse(data: EvaluateResponse): {
  kind: EvaluateOutcomeKind;
  errorCount: number;
} {
  const errorCount = data.runs.reduce((n, run) => {
    const itemErrors = run.results.filter(
      (r) => (r.label ?? "").toUpperCase() === "ERROR",
    ).length;
    return n + itemErrors;
  }, 0);
  const runError = data.runs.some((r) => r.status.toLowerCase() === "error");
  const experimentFailed = data.experiment.status.toLowerCase() === "failed";

  if (experimentFailed || runError || errorCount > 0) {
    return { kind: "with_errors", errorCount };
  }
  return { kind: "success", errorCount: 0 };
}

/** Toast success or warning based on evaluate / evaluate-pack response body. */
export function toastEvaluateOutcome(
  data: EvaluateResponse,
  copy: { success: string; withErrors: string },
): void {
  const outcome = classifyEvaluateResponse(data);
  if (outcome.kind === "with_errors") {
    toast.warning(copy.withErrors, {
      description:
        outcome.errorCount > 0
          ? `${outcome.errorCount} item error${outcome.errorCount === 1 ? "" : "s"}`
          : undefined,
    });
    return;
  }
  toast.success(copy.success);
}
