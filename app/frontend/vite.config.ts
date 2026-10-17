import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build into dist/ for nginx (ADR 0012). The development server forwards API requests to the backend.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    chunkSizeWarningLimit: 1200, // three.js stays in the lazy-loaded 3D chunk.
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
