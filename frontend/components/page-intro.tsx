import type { ReactNode } from "react";
import { PageHeader } from "@/components/page-header";

/** Top-level page title + one-line explanation of what the page is for. */
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
