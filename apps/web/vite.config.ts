import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // Three.js is isolated to a lazy route and enforced by check:bundle.
    chunkSizeWarningLimit: 1_000,
  },
  server: {
    allowedHosts: ["web"],
    proxy: {
      "/api": {
        target: "http://api:8000",
        changeOrigin: true,
      },
    },
  },
});
