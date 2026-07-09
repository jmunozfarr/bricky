import babel from "@rolldown/plugin-babel";
import { defineConfig } from "vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";

// React Three Fiber components imperatively mutate three.js objects, which
// the React Compiler's immutability model cannot reason about (the same
// boundary carve-out as react-hooks/immutability in eslint.config.js), so
// the viewer stack is excluded from compilation.
const compilerPreset = reactCompilerPreset();
compilerPreset.rolldown.filter = {
  ...compilerPreset.rolldown.filter,
  id: { exclude: ["**/src/components/ldraw/**"] },
};

export default defineConfig({
  plugins: [react(), babel({ presets: [compilerPreset] })],
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
