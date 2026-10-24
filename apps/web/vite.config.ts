import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Written on every production build so bundle regressions are visible
    // rather than discovered in the field.
    visualizer({ filename: "dist/stats.html", gzipSize: true, brotliSize: true }),
  ],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev, so the browser never needs a CORS preflight and
      // the dev setup matches production (CDN + API behind one hostname).
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Pinned so a stray static import cannot pull these into the entry
        // chunk. A Flat Owner must never download the Bill Builder or charts.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\/]node_modules[\/](react|react-dom|react-router|react-router-dom|scheduler)[\/]/.test(id))
            return "react-vendor";
          if (/[\/]node_modules[\/](@reduxjs|react-redux|redux|immer|reselect)[\/]/.test(id))
            return "state-vendor";
          if (/[\/]node_modules[\/](recharts|d3-|victory-)/.test(id)) return "charts";
          if (/[\/]node_modules[\/]@dnd-kit[\/]/.test(id)) return "dnd";
          if (/[\/]node_modules[\/](firebase|@firebase)[\/]/.test(id)) return "firebase";
          return undefined;
        },
      },
    },
  },
});
