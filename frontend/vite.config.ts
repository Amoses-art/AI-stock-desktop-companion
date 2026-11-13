import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Tauri dev server 约定端口（与 src-tauri/tauri.conf.json 的 devUrl 对齐）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  // 生产构建禁止内联大资源，保证 CSP 'self' 下可用
  build: {
    assetsInlineLimit: 0,
  },
});
