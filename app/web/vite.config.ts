import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build landet im Python-Paket, FastAPI liefert ihn aus (ADR 0010). `npm run dev` leitet /api an `uv run drawing-demo` weiter.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/drawing_demo/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200, // three.js im nachgeladenen 3D-Chunk
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
