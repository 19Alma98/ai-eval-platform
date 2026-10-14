"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Database,
  FileCode,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  ListTree,
  Radio,
  ShieldCheck,
} from "lucide-react";
import { ProjectSwitcher } from "@/components/project-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/cn";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";

type NavItem = {
  href: string;
  label: string;
  icon: typeof Database;
  hint: string;
};

const NAV: { section: string | null; items: NavItem[] }[] = [
  {
    section: null,
    items: [
      {
        href: "/overview",
        label: "Overview",
        icon: LayoutDashboard,
        hint: "Health of your RAG app at a glance",
      },
    ],
  },
  {
    section: "Evaluate",
    items: [
      {
        href: "/datasets",
        label: "Test sets",
        icon: Database,
        hint: "Questions with expected answers and documents",
      },
      {
        href: "/experiments",
        label: "Experiments",
        icon: FlaskConical,
        hint: "Run your app on a test set and score it",
      },
      {
        href: "/release",
        label: "Release gate",
        icon: ShieldCheck,
        hint: "Decide if a version is good enough to ship",
      },
    ],
  },
  {
    section: "Monitor",
    items: [
      {
        href: "/live-runs",
        label: "Live traffic",
        icon: Radio,
        hint: "Real user questions scored by an LLM judge",
      },
      {
        href: "/traces",
        label: "Traces",
        icon: ListTree,
        hint: "Every call step by step: retrieval, prompt, answer",
      },
      {
        href: "/monitoring",
        label: "Production",
        icon: Activity,
        hint: "Latency, cost and quality over time, alarms and review queue",
      },
    ],
  },
  {
    section: "Configure",
    items: [
      {
        href: "/metrics",
        label: "Metrics",
        icon: Gauge,
        hint: "What you measure and the pass thresholds",
      },
      {
        href: "/app-configs",
        label: "App configs",
        icon: FileCode,
        hint: "Versioned prompts, models and retrieval settings",
      },
    ],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { projectId } = useProjectId();

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="sticky top-0 flex h-screen w-[220px] shrink-0 flex-col border-r border-border bg-surface">
        <Link
          href={withProjectQuery("/overview", projectId)}
          className="flex h-14 items-center gap-2 border-b border-border px-4"
        >
          <span
            aria-hidden
            className="flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground"
          >
            AE
          </span>
          <span className="text-sm font-semibold tracking-tight text-foreground">
            AI Eval
          </span>
        </Link>
        <nav aria-label="Main" className="flex flex-1 flex-col gap-4 overflow-y-auto p-3">
          {NAV.map(({ section, items }) => (
            <div key={section ?? "root"} className="flex flex-col gap-0.5">
              {section ? (
                <span className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  {section}
                </span>
              ) : null}
              {items.map(({ href, label, icon: Icon, hint }) => {
                const active =
                  pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    key={href}
                    href={withProjectQuery(href, projectId)}
                    title={hint}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-row-hover hover:text-foreground",
                      active && "bg-row-selected font-medium text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface/95 px-6 backdrop-blur">
          <ProjectSwitcher />
          <div className="flex-1" />
          <ThemeToggle />
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
