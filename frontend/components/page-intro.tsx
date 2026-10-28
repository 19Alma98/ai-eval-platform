import type { ReactNode } from "react";
import { PageHeader } from "@/components/page-header";

export function PageIntro({
  title,
  glossary,
  actions,
}: {
  title: string;
  glossary: string;
  actions?: ReactNode;
}) {
  return <PageHeader title={title} description={glossary} actions={actions} />;
}
