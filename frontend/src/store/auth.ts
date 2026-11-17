import { create } from "zustand";
import { api, type Account } from "../api/client";

interface AuthState {
  /** the answer of the server to "who am I?" (null until it has answered) */
  account: Account | null;
  /** the server could not be asked */
  error: string | null;
  load: () => Promise<void>;
  /** after the session ended behind our back (another tab logged out, the session expired) */
  expire: () => void;
  logout: () => Promise<void>;
}

export const useAuth = create<AuthState>((set, get) => ({
  account: null,
  error: null,
  load: async () => {
    try {
      set({ account: await api.account(), error: null });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Something went wrong" });
    }
  },
  expire: () => {
    const a = get().account;
    if (a && a.user) set({ account: { ...a, user: null, usage: undefined } });
  },
  logout: async () => {
    try {
      await api.logout();
    } finally {
      await get().load();
    }
  },
}));
