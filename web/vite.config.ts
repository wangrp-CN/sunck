import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { elementPlusPlugins } from "./vite.ep";

// 前端工程骨架配置（方案 A 原生服务）
// 开发代理：将 /api 转发到本地 FastAPI（默认 8000 端口）
export default defineConfig({
  plugins: [vue(), ...elementPlusPlugins()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      // 实时 WebSocket：开发期与 /api 同样转发到后端 8000，
      // 配合前端 ws.ts 用 window.location 同源连接，生产期由 nginx /ws 反代。
      "/ws": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // 拆分 vendor，提升缓存命中与并行加载，消除单 chunk >500KB 警告
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          // 注意顺序：icons-vue 路径含 "element-plus"，须先于通用规则判定
          if (id.includes("@element-plus/icons-vue")) return "vendor-element-icons";
          if (id.includes("element-plus")) {
            // 进一步拆分 element-plus 本体，避免单 chunk > 500KB：
            // 组件按名称稳定分桶到 3 个 chunk，公共模块（utils/hooks/locale 等）单独成核
            if (id.includes("/es/components/")) {
              const m = id.match(/element-plus[\\/]es[\\/]components[\\/]([^\\/]+)/);
              const name = m ? m[1] : "misc";
              let h = 0;
              for (let i = 0; i < name.length; i++) {
                h = (h * 31 + name.charCodeAt(i)) >>> 0;
              }
              return `vendor-ep-c${h % 3}`;
            }
            return "vendor-ep-core";
          }
          if (
            id.includes("vue-router") ||
            id.includes("/vue/") ||
            id.includes("@vue") ||
            id.includes("pinia") ||
            id.includes("vue-demi")
          ) {
            return "vendor-vue";
          }
          if (id.includes("axios")) return "vendor-axios";
          return "vendor";
        },
      },
      // element-plus 组件之间天然互相引用，按组件名分桶会产生「良性循环 chunk」警告；
      // 该警告为良性——Rollup 会自动处理加载顺序，不影响运行。仅抑制此特定警告，
      // 其余警告（含 >500KB 超体积）仍照常报错，保留体积守卫。
      onwarn(warning, defaultHandler) {
        const msg = typeof warning.message === "string" ? warning.message : "";
        if (msg.includes("Circular chunk") && msg.includes("vendor-ep-")) {
          return;
        }
        defaultHandler(warning);
      },
    },
  },
});
