import type { TraceScoreSummary } from "@/lib/api/types";
import { formatPercent, formatScore } from "@/lib/format";

export type ProductionScoreRow = {
  key: string;
  label: string;
  count: number;
  primary: string;
  secondary: string | null;
};

/** Overview rows: user feedback first (as % positive), then metrics by name. */
export function productionScoreRows(summary: TraceScoreSummary | undefined): ProductionScoreRow[] {
  const rows = summary?.rows ?? [];
  const feedback = rows.filter((r) => r.name === "user_feedback");
  const metrics = rows.filter((r) => r.name !== "user_feedback");
  return [
    ...feedback.map((r) => ({
      key: `${r.name}:${r.source}`,
      label: r.source === "human" ? "User feedback" : `User feedback (${r.source})`,
      count: r.count,
      primary: r.pass_rate == null ? "—" : `${formatPercent(r.pass_rate)} positive`,
      secondary: null,
    })),
    ...metrics.map((r) => ({
      key: `${r.name}:${r.source}`,
      label: r.source === "sdk" ? r.name : `${r.name} (${r.source})`,
      count: r.count,
      primary: `${formatScore(r.mean)} mean`,
      secondary: r.pass_rate == null ? null : `${formatPercent(r.pass_rate)} pass`,
    })),
  ];
}
