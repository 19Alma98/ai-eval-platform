"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <Button
      variant="outline"
      size="icon-sm"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      // The server can't know the theme, so the markup must not depend on it:
      // both icons render and CSS shows the right one (no hydration mismatch).
      aria-label="Toggle light or dark theme"
    >
      <Moon className="size-3.5 dark:hidden" aria-hidden />
      <Sun className="hidden size-3.5 dark:block" aria-hidden />
    </Button>
  );
}
