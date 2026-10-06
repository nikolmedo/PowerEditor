import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API_TARGET = "http://127.0.0.1:8765";

// The backend must run with `powereditor serve --dev` so it accepts the Vite origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true, ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
  },
});
