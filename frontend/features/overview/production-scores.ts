import type { TraceScoreSummary } from "@/lib/api/types";
import { formatScore } from "@/lib/format";

export type ProductionScoreRow = {
  key: string;
  label: string;
  count: number;
  primary: string;
  secondary: string | null;
};

const pct = (rate: number) => `${Math.round(rate * 100)}%`;

/** Overview rows: user feedback first (as % positive), then metrics by name. */
export function productionScoreRows(summary: TraceScoreSummary | undefined): ProductionScoreRow[] {
  const rows = summary?.rows ?? [];
  const feedback = rows.filter((r) => r.name === "user_feedback");
  const metrics = rows.filter((r) => r.name !== "user_feedback");
  return [
    ...feedback.map((r) => ({
      key: `${r.name}:${r.source}`,
      label: "User feedback",
      count: r.count,
      primary: r.mean == null ? "—" : `${pct(r.mean)} positive`,
      secondary: null,
    })),
    ...metrics.map((r) => ({
      key: `${r.name}:${r.source}`,
      label: r.source === "sdk" ? r.name : `${r.name} (${r.source})`,
      count: r.count,
      primary: `${formatScore(r.mean)} mean`,
      secondary: r.pass_rate == null ? null : `${pct(r.pass_rate)} pass`,
    })),
  ];
}
