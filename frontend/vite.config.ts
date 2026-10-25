import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Served by the backend (app/main.py). Not committed; built at release time.
    outDir: "../backend/app/static",
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: {
      // The backend only accepts its own Host/Origin (DNS-rebinding + CSRF protection).
      "/api": { target: backend, changeOrigin: true, headers: { Origin: backend } },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
