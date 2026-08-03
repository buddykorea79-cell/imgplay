import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 백엔드가 파이썬이라 서버가 둘로 나뉩니다. 개발 중에는 /api를 프록시하고,
// 프로덕션 빌드(dist/)는 FastAPI가 정적 서빙해 단일 프로세스로 합칩니다.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
