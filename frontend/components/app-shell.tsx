"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Database,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  ShieldCheck,
} from "lucide-react";
import { ProjectSwitcher } from "@/components/project-switcher";
import { RefreshControl } from "@/components/refresh-control";
import { ThemeToggle } from "@/components/theme-toggle";
import { TimeRangePicker } from "@/components/time-range-picker";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/traces", label: "Traces", icon: GitBranch },
  { href: "/datasets", label: "Datasets", icon: Database },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/release", label: "Release", icon: ShieldCheck },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const project = searchParams.get("project");
  const query = project ? `?project=${encodeURIComponent(project)}` : "";

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="flex w-[200px] shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex h-12 items-center border-b border-border px-4">
          <span className="text-sm font-semibold tracking-tight text-foreground">
            AI Eval
          </span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 p-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={`${href}${query}`}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-row-hover hover:text-foreground",
                  active && "bg-row-selected font-medium text-foreground",
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
          <ProjectSwitcher />
          <Separator orientation="vertical" className="h-5" />
          <TimeRangePicker />
          <div className="flex-1" />
          <RefreshControl />
          <ThemeToggle />
        </header>
        <main className="flex-1 overflow-auto p-4">{children}</main>
      </div>
    </div>
  );
}
