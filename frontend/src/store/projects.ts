import { create } from "zustand";
import { api } from "../api/client";
import type { Project } from "../api/types";

interface ProjectsState {
  projects: Project[];
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  upsert: (p: Project) => void;
  remove: (id: string) => Promise<void>;
}

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export const useProjects = create<ProjectsState>((set) => ({
  projects: [],
  loading: false,
  error: null,
  load: async () => {
    set({ loading: true });
    try {
      set({ projects: await api.listProjects(), error: null, loading: false });
    } catch (e) {
      set({ error: message(e), loading: false });
    }
  },
  upsert: (p) =>
    set((s) => ({
      projects: s.projects.some((x) => x.id === p.id)
        ? s.projects.map((x) => (x.id === p.id ? p : x))
        : [p, ...s.projects],
    })),
  remove: async (id) => {
    try {
      await api.deleteProject(id);
      set((s) => ({ projects: s.projects.filter((p) => p.id !== id), error: null }));
    } catch (e) {
      set({ error: message(e) });
    }
  },
}));
