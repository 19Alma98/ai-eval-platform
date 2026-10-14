"use client";

import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

function snippet(experimentId: string, datasetId: string, projectSlug: string | null): string {
  const initLine = projectSlug
    ? `opengrade.init(project_slug="${projectSlug}")`
    : "opengrade.init()  # set OPENGRADE_PROJECT_SLUG";
  return `import opengrade
from opengrade import Client

${initLine}

@opengrade.trace
def answer(item):
    opengrade.bind_evaluation(
        experiment_id="${experimentId}",
        dataset_item_id=item.id,
    )
    docs = retrieve(item.input)            # your retriever
    opengrade.set_retrieval_documents(docs)    # [{"id", "title", "text"}]
    reply = generate(item.input, docs)     # your LLM call
    opengrade.set_output(reply)
    return reply

with Client() as client:
    for item in client.datasets.get("${datasetId}").items:
        answer(item)
opengrade.flush()`;
}

/**
 * Shown while an experiment has no answers yet: the experiment exists, but the app
 * has to run on the test set before anything can be scored.
 */
export function ConnectAppCard({
  experimentId,
  datasetId,
  projectSlug,
  nQuestions,
}: {
  experimentId: string;
  datasetId: string;
  projectSlug: string | null;
  nQuestions: number;
}) {
  const code = snippet(experimentId, datasetId, projectSlug);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      toast.success("Code copied");
    } catch {
      toast.error("Could not copy");
    }
  }

  return (
    <section className="grid gap-4 rounded-lg border border-primary/30 bg-surface p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-foreground">
          Next step: run your app on the test set
        </h2>
        <p className="text-sm text-muted-foreground">
          This experiment is waiting for answers. Run your app on the{" "}
          {nQuestions > 0 ? `${nQuestions} questions` : "questions"} of the test
          set with the SDK. Answers and retrieved documents show up here as they
          arrive.
        </p>
        <ol className="flex flex-col gap-2 text-sm text-foreground">
          <li className="flex gap-2">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              1
            </span>
            Install the SDK: <code className="rounded bg-surface-2 px-1">pip install opengrade-ai</code>
          </li>
          <li className="flex gap-2">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              2
            </span>
            Wrap your RAG pipeline as in the example and run it.
          </li>
          <li className="flex gap-2">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              3
            </span>
            Come back and click <strong>Score answers</strong>.
          </li>
        </ol>
      </div>
      <div className="relative min-w-0">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="absolute top-2 right-2 h-7"
          onClick={copy}
        >
          <Copy className="size-3.5" />
          Copy
        </Button>
        <pre className="max-h-[340px] overflow-auto rounded-md bg-surface-2 p-3 pr-20 text-xs leading-relaxed text-foreground">
          <code>{code}</code>
        </pre>
      </div>
    </section>
  );
}
