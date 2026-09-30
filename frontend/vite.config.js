import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies the API (and its WebSocket) to FastAPI on :8000, so the
// browser talks to one origin. Override with VITE_API_BASE for other setups.
const api = process.env.GUARDIAN_API || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/servers": api,
      "/health": api,
      "/ws": { target: api.replace(/^http/, "ws"), ws: true },
    },
  },
});
