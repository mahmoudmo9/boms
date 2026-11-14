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
    rollupOptions: {
      output: {
        // v0.10.1 section 0.3.4: pages are lazy routes (App.tsx); the libraries, the charts and the AI review (with
        // its PDF page viewer, lazy in AiActions) are chunks of their own, loaded only when used.
        manualChunks(id: string) {
          if (id.includes("node_modules/react") || id.includes("node_modules/scheduler") || id.includes("node_modules/react-router")) return "react";
          if (id.includes("node_modules/@tanstack")) return "tanstack";
          if (id.includes("node_modules/i18next") || id.includes("node_modules/react-i18next")) return "i18n";
          if (id.includes("node_modules/date-fns")) return "dates";
          if (id.includes("/src/design/components/charts") || id.includes("/src/design/charts")) return "charts";
          return undefined;
        },
      },
    },
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
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
