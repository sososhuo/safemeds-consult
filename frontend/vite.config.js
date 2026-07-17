import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    // 允许通过你指定的这个 ngrok 公网域名访问
    allowedHosts: ["imminent-smartly-tapering.ngrok-free.dev"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});