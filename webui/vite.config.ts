// 配置 WebUI 的 React 构建插件和开发环境的 API 转发。

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7860",
    },
  },
});

