import React, { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiJson } from "../services/apiClient";
import type { Project } from "../types";
import { ProjectsContext } from "./projects";
import type { ProjectsError } from "./projects";
import type { ProjectsState } from "./projects";

const PROJECTS_CACHE_KEY = "ainovel:projects-cache:v3";

type ProjectsCachePayload = {
  at: number;
  projects: Project[];
};

function readProjectsCache(): ProjectsCachePayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PROJECTS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ProjectsCachePayload;
    if (!parsed || typeof parsed.at !== "number" || !Array.isArray(parsed.projects)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeProjectsCache(projects: Project[]) {
  if (typeof window === "undefined") return;
  try {
    const payload: ProjectsCachePayload = {
      at: Date.now(),
      projects,
    };
    window.sessionStorage.setItem(PROJECTS_CACHE_KEY, JSON.stringify(payload));
  } catch {
    // ignore storage failures
  }
}

export function ProjectsProvider(props: { children: React.ReactNode }) {
  const cached = readProjectsCache();
  const [projects, setProjects] = useState<Project[]>(() => cached?.projects ?? []);
  const [loading, setLoading] = useState(() => !cached);
  const [error, setError] = useState<ProjectsError | null>(null);

  const refresh = useCallback(async () => {
    const hasCachedProjects = projects.length > 0;
    setLoading((prev) => (hasCachedProjects ? prev : true));
    if (!hasCachedProjects) setError(null);
    try {
      const res = await apiJson<{ projects: Project[] }>("/api/projects", { timeoutMs: 15_000 });
      const nextProjects = res.data.projects ?? [];
      setProjects(nextProjects);
      writeProjectsCache(nextProjects);
      setError(null);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      if (!hasCachedProjects) {
        setError({
          code: err?.code ?? "UNKNOWN_ERROR",
          message: err?.message ?? "加载项目失败，请稍后重试",
          requestId: err?.requestId ?? "unknown",
        });
      }
    } finally {
      setLoading(false);
    }
  }, [projects.length]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<ProjectsState>(
    () => ({ projects, loading, error, refresh }),
    [projects, loading, error, refresh],
  );
  return <ProjectsContext.Provider value={value}>{props.children}</ProjectsContext.Provider>;
}
