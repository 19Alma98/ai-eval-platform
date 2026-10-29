import { GitCommitHorizontal } from "lucide-react";
import type { ExperimentCommit } from "./experiment-meta";

export function CommitLabel({ commit }: { commit: ExperimentCommit }) {
  const sha = <span className="font-mono">{commit.short}</span>;
  return (
    <span className="inline-flex min-w-0 items-center gap-1" title={commit.sha}>
      <GitCommitHorizontal className="size-3.5 shrink-0" aria-hidden />
      {commit.href ? (
        <a
          href={commit.href}
          target="_blank"
          rel="noreferrer"
          className="hover:text-primary hover:underline"
        >
          {sha}
        </a>
      ) : (
        sha
      )}
      {commit.branch ? <span className="truncate">({commit.branch})</span> : null}
      {commit.dirty ? (
        <span
          className="text-status-warn"
          title="The run had uncommitted changes on top of this commit"
        >
          + uncommitted
        </span>
      ) : null}
    </span>
  );
}
