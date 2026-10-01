"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { TimeRangeProvider } from "@/lib/time-range-context";
import { ThemeProvider } from "@/lib/theme";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <TimeRangeProvider>
          <TooltipProvider>
            <Suspense fallback={null}>{children}</Suspense>
            <Toaster richColors closeButton position="bottom-right" />
          </TooltipProvider>
        </TimeRangeProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
