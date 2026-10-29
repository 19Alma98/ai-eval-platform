"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { History, Tag } from "lucide-react";
import { toast } from "sonner";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import { setExperimentAlias } from "@/lib/api/experiment-aliases";
import type { Experiment, ExperimentAlias } from "@/lib/api/types";
import { resolveLabel } from "@/lib/format";
import {
  MAIN_ALIAS,
  PRESET_EXPERIMENT_ALIASES,
  isExamMismatchError,
  isExperimentPromotable,
} from "./experiment-aliases";
import {
  experimentAliasHistoryQueryKey,
  experimentAliasesQueryKey,
  useDeleteExperimentAlias,
  useExperimentAliasHistory,
  useExperimentAliases,
  useSetExperimentAlias,
} from "./use-experiment-aliases";

export function ExperimentAliasBadges({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <span className="mt-0.5 flex flex-wrap gap-1">
      {names.map((name) => (
        <Badge
          key={name}
          variant={name === MAIN_ALIAS ? "default" : "outline"}
          className="font-mono"
        >
          {name}
        </Badge>
      ))}
    </span>
  );
}

type ExperimentAliasActionsProps = {
  projectId: string;
  experiment: Experiment;
  experimentNames: Map<string, string>;
};

export function ExperimentAliasActions({
  projectId,
  experiment,
  experimentNames,
}: ExperimentAliasActionsProps) {
  const queryClient = useQueryClient();
  const aliasesQuery = useExperimentAliases(projectId);
  const setAlias = useSetExperimentAlias(projectId);
  const deleteAlias = useDeleteExperimentAlias(projectId);

  const [promoteOpen, setPromoteOpen] = useState(false);
  const [promoteNote, setPromoteNote] = useState("");
  const [forceConfirmOpen, setForceConfirmOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyAlias, setHistoryAlias] = useState(MAIN_ALIAS);
  const [aliasPreset, setAliasPreset] = useState<string>(MAIN_ALIAS);
  const [customAlias, setCustomAlias] = useState("");

  const aliases = aliasesQuery.data ?? [];
  const pointingHere = useMemo(
    () => aliases.filter((a) => a.experiment_id === experiment.id).map((a) => a.name),
    [aliases, experiment.id],
  );
  const isMain = pointingHere.includes(MAIN_ALIAS);
  const promotable = isExperimentPromotable(experiment.status);
  const effectiveAlias =
    aliasPreset === "custom" ? customAlias.trim() : aliasPreset;

  async function putAlias(opts: {
    alias: string;
    note?: string | null;
    force?: boolean;
  }) {
    const result = await setExperimentAlias(projectId, opts.alias, {
      experiment_id: experiment.id,
      note: opts.note ?? null,
      force: opts.force ?? false,
    });
    await queryClient.invalidateQueries({
      queryKey: experimentAliasesQueryKey(projectId),
    });
    await queryClient.invalidateQueries({
      queryKey: experimentAliasHistoryQueryKey(projectId, opts.alias),
    });
    if (result.changed === false) {
      toast.message(`Alias “${opts.alias}” already points here`);
    } else {
      toast.success(`Alias “${opts.alias}” updated`);
    }
    return result;
  }

  async function handlePromote(force: boolean) {
    const note = promoteNote.trim() || null;
    try {
      await putAlias({
        alias: MAIN_ALIAS,
        note: force ? note || "exam changed" : note,
        force,
      });
      setPromoteOpen(false);
      setForceConfirmOpen(false);
      setPromoteNote("");
    } catch (err) {
      if (
        !force &&
        err instanceof ApiError &&
        err.status === 400 &&
        isExamMismatchError(err.message)
      ) {
        setPromoteOpen(false);
        setForceConfirmOpen(true);
        return;
      }
      toast.error(formatErrorForUi(err));
    }
  }

  function handleSetManagedAlias() {
    if (!effectiveAlias || !promotable) return;
    setAlias.mutate(
      { alias: effectiveAlias, experiment_id: experiment.id },
      {
        onSuccess: () => {
          setManageOpen(false);
          setCustomAlias("");
          setAliasPreset(MAIN_ALIAS);
        },
      },
    );
  }

  return (
    <>
      {pointingHere.length > 0 ? (
        <span className="flex flex-wrap items-center gap-1">
          <ExperimentAliasBadges names={pointingHere} />
        </span>
      ) : null}

      {promotable && !isMain ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setPromoteOpen(true)}
          disabled={setAlias.isPending}
        >
          <Tag className="size-4" />
          Set as main
        </Button>
      ) : null}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setManageOpen(true)}
      >
        Manage aliases…
      </Button>

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          setHistoryAlias(
            pointingHere.includes(MAIN_ALIAS)
              ? MAIN_ALIAS
              : (pointingHere[0] ?? MAIN_ALIAS),
          );
          setHistoryOpen(true);
        }}
      >
        <History className="size-4" />
        Alias history
      </Button>

      <Dialog open={promoteOpen} onOpenChange={setPromoteOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Set as main baseline</DialogTitle>
            <DialogDescription>
              Move the <span className="font-mono">main</span> alias to this
              experiment. CI and compare can use{" "}
              <span className="font-mono">alias:main</span> against it.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <label htmlFor="promote-note" className="text-sm font-medium">
              Note <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <Input
              id="promote-note"
              value={promoteNote}
              onChange={(e) => setPromoteNote(e.target.value)}
              placeholder="e.g. accepted after release gate"
              maxLength={2000}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPromoteOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handlePromote(false)}
              disabled={setAlias.isPending}
            >
              Set as main
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={forceConfirmOpen} onOpenChange={setForceConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Exam differs from current main</DialogTitle>
            <DialogDescription>
              This experiment uses a different test set or metrics set than the
              experiment <span className="font-mono">main</span> points to.
              Moving the alias anyway means future regressions compare different
              exams.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setForceConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handlePromote(true)}
            >
              Move anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={manageOpen} onOpenChange={setManageOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Manage aliases</DialogTitle>
            <DialogDescription>
              Named pointers to this experiment (same idea as app-config aliases).
            </DialogDescription>
          </DialogHeader>

          {pointingHere.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {pointingHere.map((name) => (
                <span
                  key={name}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
                >
                  <span className="font-mono">{name}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-6 px-1.5 text-muted-foreground"
                    aria-label={`Remove alias ${name}`}
                    disabled={deleteAlias.isPending}
                    onClick={() => deleteAlias.mutate(name)}
                  >
                    Remove
                  </Button>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No aliases point here yet.
            </p>
          )}

          <div className="flex flex-wrap items-end gap-3 border-t border-border pt-3">
            <div className="w-[160px]">
              <label className="mb-1 block text-xs text-muted-foreground">
                Alias
              </label>
              <Select
                value={aliasPreset}
                onValueChange={(v) => setAliasPreset(v ?? MAIN_ALIAS)}
              >
                <SelectTrigger aria-label="Alias preset">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRESET_EXPERIMENT_ALIASES.map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                  <SelectItem value="custom">Custom…</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {aliasPreset === "custom" ? (
              <div className="w-[180px]">
                <label
                  htmlFor="custom-experiment-alias"
                  className="mb-1 block text-xs text-muted-foreground"
                >
                  Name
                </label>
                <Input
                  id="custom-experiment-alias"
                  value={customAlias}
                  onChange={(e) => setCustomAlias(e.target.value)}
                  placeholder="e.g. staging"
                />
              </div>
            ) : null}
            <Button
              type="button"
              disabled={
                !effectiveAlias || !promotable || setAlias.isPending
              }
              title={
                !promotable
                  ? "Running, failed, or cancelled experiments cannot be aliased"
                  : undefined
              }
              onClick={handleSetManagedAlias}
            >
              {setAlias.isPending ? "Saving…" : "Set alias"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AliasHistoryDialog
        projectId={projectId}
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        alias={historyAlias}
        onAliasChange={setHistoryAlias}
        aliases={aliases}
        experimentNames={experimentNames}
      />
    </>
  );
}

function AliasHistoryDialog({
  projectId,
  open,
  onOpenChange,
  alias,
  onAliasChange,
  aliases,
  experimentNames,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  alias: string;
  onAliasChange: (alias: string) => void;
  aliases: ExperimentAlias[];
  experimentNames: Map<string, string>;
}) {
  const historyQuery = useExperimentAliasHistory(
    open ? projectId : null,
    open ? alias : null,
  );
  const setAlias = useSetExperimentAlias(projectId);
  const events = historyQuery.data ?? [];
  const aliasNames = useMemo(() => {
    const names = new Set(aliases.map((a) => a.name));
    names.add(MAIN_ALIAS);
    names.add(alias);
    return [...names].sort((a, b) => {
      if (a === MAIN_ALIAS) return -1;
      if (b === MAIN_ALIAS) return 1;
      return a.localeCompare(b);
    });
  }, [aliases, alias]);

  function canRestore(previousId: string | null): boolean {
    if (!previousId) return false;
    // We only know status if the experiment is still listed; allow restore when
    // the id exists in the name map (still in project). Server re-checks status.
    return experimentNames.has(previousId);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Alias history</DialogTitle>
          <DialogDescription>
            Each row is a move of the alias. Restore points it back at the
            previous experiment.
          </DialogDescription>
        </DialogHeader>

        <div className="w-[180px]">
          <label className="mb-1 block text-xs text-muted-foreground">
            Alias
          </label>
          <Select value={alias} onValueChange={(v) => v && onAliasChange(v)}>
            <SelectTrigger aria-label="Alias for history">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {aliasNames.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {historyQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading history…</p>
        ) : historyQuery.isError ? (
          <p className="text-sm text-destructive">
            {formatErrorForUi(historyQuery.error)}
          </p>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No history for <span className="font-mono">{alias}</span> yet.
          </p>
        ) : (
          <ul className="max-h-[360px] space-y-2 overflow-y-auto">
            {events.map((event) => {
              const previousId = event.previous_experiment_id;
              return (
                <li
                  key={event.id}
                  className="rounded-md border border-border px-3 py-2 text-sm"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium text-foreground">
                      →{" "}
                      {resolveLabel(
                        event.experiment_id,
                        experimentNames,
                        event.experiment_id.slice(0, 8),
                      )}
                    </span>
                    <RelativeTime date={event.created_at} />
                  </div>
                  {previousId ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      from{" "}
                      {resolveLabel(
                        previousId,
                        experimentNames,
                        previousId.slice(0, 8),
                      )}
                    </p>
                  ) : (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      first assignment
                    </p>
                  )}
                  {event.note ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {event.note}
                    </p>
                  ) : null}
                  {canRestore(previousId) ? (
                    <div className="mt-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={setAlias.isPending}
                        onClick={() =>
                          setAlias.mutate({
                            alias,
                            experiment_id: previousId!,
                            note: "rollback from UI",
                          })
                        }
                      >
                        Restore previous
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
