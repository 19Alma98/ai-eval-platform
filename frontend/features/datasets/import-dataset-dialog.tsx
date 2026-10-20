"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Lock, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type SubmitEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatErrorForUi } from "@/lib/api/client";
import { importDatasetItems } from "@/lib/api/datasets";
import { withProjectQuery } from "@/lib/project-href";
import { RAG_QA_TASK } from "./rag-qa";
import { datasetQueryKey, datasetsQueryKey } from "./use-datasets";

// The SDK names these input / expected_output; the importer accepts both spellings.
const IMPORT_COLUMNS = [
  { name: "question", alias: "input", help: "What the user asks (required)" },
  { name: "expected_answer", alias: "expected_output", help: "The correct answer (required)" },
  { name: "expected_doc_ids", help: "IDs of the documents that contain the answer" },
  { name: "must_contain", help: "Phrases the answer must include (optional)" },
] as const;

const TEMPLATE_CSV = [
  "question,expected_answer,expected_doc_ids,must_contain",
  "How many vacation days do I get?,Full-time employees get 20 days per year.,pto,20 days",
  "Which VPN should I use?,Use the company GlobalProtect VPN.,vpn|it-security,GlobalProtect",
].join("\n");

function downloadTemplate() {
  const blob = new Blob([`${TEMPLATE_CSV}\n`], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "test-set-template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export function ImportDatasetDialog({
  projectId,
  datasetId,
  datasetName,
  taskType,
  locked = false,
  version,
  open,
  onOpenChange,
  showTrigger = true,
}: {
  projectId: string;
  datasetId: string;
  datasetName?: string;
  taskType: string | null;
  /** Experiments were scored on this version: the import goes into a newer version. */
  locked?: boolean;
  version?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  showTrigger?: boolean;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [importErrors, setImportErrors] = useState<
    { row: number; message: string }[]
  >([]);

  const canImport = taskType === RAG_QA_TASK;

  const importMutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a file");
      return importDatasetItems(datasetId, file);
    },
    onSuccess: async (result) => {
      // Import may land on another row (fork, or the writable tip of the same name).
      const moved = result.dataset_id !== datasetId;
      await queryClient.invalidateQueries({
        queryKey: datasetQueryKey(datasetId),
      });
      if (moved) {
        await queryClient.invalidateQueries({
          queryKey: datasetQueryKey(result.dataset_id),
        });
      }
      await queryClient.invalidateQueries({
        queryKey: datasetsQueryKey(projectId),
      });
      setImportErrors(result.errors);
      if (moved && result.created > 0) {
        toast.success(
          `Imported ${result.created} question${result.created === 1 ? "" : "s"} into new version v${result.version}`,
        );
      } else if (result.created > 0) {
        toast.success(
          `Imported ${result.created} question${result.created === 1 ? "" : "s"}`,
        );
      }
      if (result.errors.length > 0) {
        toast.warning(
          `${result.errors.length} row${result.errors.length === 1 ? "" : "s"} skipped`,
        );
      }
      if (result.created > 0 && result.errors.length === 0) {
        setFile(null);
        onOpenChange(false);
      }
      if (moved) {
        router.push(
          withProjectQuery(`/datasets/${result.dataset_id}`, projectId),
        );
      }
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
      toast.error(message);
    },
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!file || !canImport) return;
    setImportErrors([]);
    importMutation.mutate();
  }

  function handleOpenChange(next: boolean) {
    if (!next) {
      setFile(null);
      setImportErrors([]);
    }
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      {showTrigger ? (
        <DialogTrigger
          render={
            <Button
              type="button"
              size="sm"
              disabled={!canImport}
              title={
                canImport
                  ? undefined
                  : "Import is available for this test set only after it is created as RAG Q&A"
              }
            >
              <Upload className="size-4" />
              Import questions
            </Button>
          }
        />
      ) : null}
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Import questions</DialogTitle>
            <DialogDescription>
              Upload a CSV or JSON file
              {datasetName ? (
                <>
                  {" "}into{" "}
                  <span className="font-medium text-foreground">{datasetName}</span>
                </>
              ) : null}
              . One row per question.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            {locked ? (
              <p
                role="note"
                className="flex items-start gap-2 rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-xs text-status-warn"
              >
                <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>
                  {version != null ? `v${version}` : "This version"} is locked because experiments
                  were scored on it. The questions go into a newer version of this test set
                  (created if needed, starting from the latest questions) and you&apos;ll be taken
                  there, so past results stay comparable.
                </span>
              </p>
            ) : null}
            <div className="flex flex-col gap-2">
              <label htmlFor="dataset-import-file" className="text-sm font-medium">
                File (.csv or .json)
              </label>
              <Input
                id="dataset-import-file"
                key={open ? "open" : "closed"}
                type="file"
                accept=".csv,.json,text/csv,application/json"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setImportErrors([]);
                }}
              />
            </div>
            <div className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-foreground">Expected columns</p>
                <button
                  type="button"
                  onClick={downloadTemplate}
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  <Download className="size-3" />
                  Download template
                </button>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-muted-foreground">
                {IMPORT_COLUMNS.map((col) => (
                  <div key={col.name} className="contents">
                    <dt className="font-mono text-foreground">
                      {col.name}
                      {"alias" in col ? (
                        <span className="font-sans text-muted-foreground"> or </span>
                      ) : null}
                      {"alias" in col ? col.alias : null}
                    </dt>
                    <dd>{col.help}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-muted-foreground">
                In CSV, separate multiple values with “|”. In JSON, use arrays.
              </p>
            </div>
            {importErrors.length > 0 ? (
              <div className="max-h-40 overflow-y-auto rounded-md border border-border bg-surface px-3 py-2 text-xs">
                <p className="mb-1 font-medium text-foreground">Row errors</p>
                <ul className="list-inside list-disc text-muted-foreground">
                  {importErrors.map((err) => (
                    <li key={`${err.row}-${err.message}`}>
                      Row {err.row}: {err.message}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!file || !canImport || importMutation.isPending}
            >
              {importMutation.isPending
                ? "Importing…"
                : locked
                  ? "Import into new version"
                  : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
