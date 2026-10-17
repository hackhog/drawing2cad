import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build nach dist/, nginx im Frontend-Container liefert ihn aus (ADR 0012). `npm run dev` leitet /api an `uv run drawing-demo` weiter.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    chunkSizeWarningLimit: 1200, // three.js im nachgeladenen 3D-Chunk
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
