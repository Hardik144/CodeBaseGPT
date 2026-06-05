import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3001,
    proxy: {
      "/api": "http://localhost:8001",
      "/health": "http://localhost:8001",
    },
  },
});
# frontend: scaffold Vite app with Dockerfile and index
# fix: update vite proxy target for local dev server
# frontend: scaffold Vite app with Dockerfile and index
# fix: update vite proxy target for local dev server
# frontend: scaffold Vite app with Dockerfile and index
# fix: update vite proxy target for local dev server
# frontend: scaffold Vite app with Dockerfile and index
# fix: update vite proxy target for local dev server
