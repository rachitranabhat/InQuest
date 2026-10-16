import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8100", changeOrigin: false } },
  },
  preview: { port: 4174, proxy: { "/api": { target: "http://127.0.0.1:8100" } } },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router"],
          charts: ["recharts"],
          graph: ["cytoscape"],
          ui: ["@radix-ui/react-dialog", "@radix-ui/react-tabs", "@radix-ui/react-tooltip", "@tanstack/react-query", "lucide-react"],
        },
      },
    },
  },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"], css: false },
} as never);
