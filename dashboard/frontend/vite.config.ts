import { execSync } from "child_process";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { defineConfig } from "vite";

const commitHash = (() => {
  const sha = process.env.RAILWAY_GIT_COMMIT_SHA;
  if (sha) return sha.slice(0, 7);
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return "dev";
  }
})();

export default defineConfig({
  plugins: [react()],
  define: {
    __COMMIT_HASH__: JSON.stringify(commitHash),
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_API_URL || "http://localhost:8000",
    },
    watch: {
      usePolling: true,
      interval: 500,
    },
  },
});
