/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks to Vite; /api is forwarded to the FastAPI server (`avc serve`),
// so there are no CORS problems and no URLs to configure. Ports are deliberately unusual
// (5173/8000 are taken by other dev servers on many machines) and strict: never shift silently.
const API = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8742";

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5742, strictPort: true, proxy: { "/api": API } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
