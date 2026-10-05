"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useState, type FormEvent } from "react";
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
import { ApiError } from "@/lib/api/client";
import { importDatasetItems } from "@/lib/api/datasets";
import { RAG_QA_TASK } from "./rag-qa";
import { datasetQueryKey, datasetsQueryKey } from "./use-datasets";

export function ImportDatasetDialog({
  projectId,
  datasetId,
  datasetName,
  taskType,
  open,
  onOpenChange,
  showTrigger = true,
}: {
  projectId: string;
  datasetId: string;
  datasetName?: string;
  taskType: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  showTrigger?: boolean;
}) {
  const queryClient = useQueryClient();
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
      await queryClient.invalidateQueries({
        queryKey: datasetQueryKey(datasetId),
      });
      await queryClient.invalidateQueries({
        queryKey: datasetsQueryKey(projectId),
      });
      setImportErrors(result.errors);
      if (result.created > 0) {
        toast.success(
          `Imported ${result.created} item${result.created === 1 ? "" : "s"}`,
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
    },
    onError: (err) => {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Import failed";
      toast.error(message);
    },
  });

  function handleSubmit(e: FormEvent) {
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
              variant="outline"
              disabled={!canImport}
              title={
                canImport
                  ? undefined
                  : "Import is available for this test set only after it is created as RAG Q&A"
              }
            >
              <Upload className="size-4" />
              Import
            </Button>
          }
        />
      ) : null}
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Import test items</DialogTitle>
            <DialogDescription>
              {datasetName ? (
                <>
                  Upload CSV or JSON for{" "}
                  <span className="font-medium text-foreground">
                    {datasetName}
                  </span>
                  . Required: question, expected_answer, expected_doc_ids.
                  Optional: must_contain.
                </>
              ) : (
                <>
                  Upload CSV or JSON with question, expected_answer,
                  expected_doc_ids, and optional must_contain.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="dataset-import-file" className="text-sm font-medium">
                File
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
              <p className="text-xs text-muted-foreground">
                CSV: pipe-separated values in expected_doc_ids and must_contain.
                JSON: arrays for the same fields.
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
              {importMutation.isPending ? "Importing…" : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
