"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const STORAGE_KEY = "aiobs.projectId";

function readStoredProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(STORAGE_KEY);
}

export function useProjectId(): {
  projectId: string | null;
  setProjectId: (id: string) => void;
  clearProjectId: () => void;
} {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const paramProject = searchParams.get("project");

  const [storedProjectId, setStoredProjectId] = useState<string | null>(() =>
    readStoredProjectId(),
  );

  const projectId = paramProject ?? storedProjectId;

  useEffect(() => {
    if (paramProject) {
      localStorage.setItem(STORAGE_KEY, paramProject);
    }
  }, [paramProject]);

  const setProjectId = useCallback(
    (id: string) => {
      setStoredProjectId(id);
      localStorage.setItem(STORAGE_KEY, id);
      const params = new URLSearchParams(searchParams.toString());
      params.set("project", id);
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const clearProjectId = useCallback(() => {
    setStoredProjectId(null);
    localStorage.removeItem(STORAGE_KEY);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("project");
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  }, [pathname, router, searchParams]);

  return { projectId, setProjectId, clearProjectId };
}
