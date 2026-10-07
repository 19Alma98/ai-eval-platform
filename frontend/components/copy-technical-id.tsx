"use client";

import type { MouseEvent } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

type CopyTechnicalIdProps = {
  id: string;
  /** Accessible label, e.g. "Copy trace ID" */
  label?: string;
  className?: string;
};

export function CopyTechnicalId({
  id,
  label = "Copy ID",
  className,
}: CopyTechnicalIdProps) {
  async function onCopy(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    try {
      await navigator.clipboard.writeText(id);
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Could not copy");
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className={cn("size-6 shrink-0", className)}
      aria-label={label}
      title={label}
      onClick={onCopy}
    >
      <Copy className="size-3" />
    </Button>
  );
}
