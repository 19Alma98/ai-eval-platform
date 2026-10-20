"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { DatasetDetailView } from "@/features/datasets/dataset-detail";
import { ErrorState } from "@/components/error-state";
import { ProjectRequired } from "@/components/project-required";
import { Button } from "@/components/ui/button";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function DatasetDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const datasetId = resolveStaticExportParam(
    params.datasetId,
    pathname,
    /^\/datasets\/([^/]+)/,
  );
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!datasetId) {
    return (
      <ErrorState
        title="Test set not found"
        message="This link does not point to a test set. Open Test sets and pick one from the list."
        action={
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href={withProjectQuery("/datasets", projectId)} />}
          >
            Back to Test sets
          </Button>
        }
      />
    );
  }

  return <DatasetDetailView projectId={projectId} datasetId={datasetId} />;
}
