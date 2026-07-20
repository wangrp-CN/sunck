import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { elementPlusPlugins } from "./vite.ep";

// 前端单元测试配置（Vitest + Vue SFC + jsdom）
export default defineConfig({
  plugins: [vue(), ...elementPlusPlugins({ importStyle: true, emitDts: false })],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["src/**/*.spec.ts"],
    clearMocks: true,
    server: {
      // 让 element-plus 走 Vite 管线处理（其按需注入的 .css 由 Vite 桩处理），
      // 避免 Node 直接加载 .css 报 "Unknown file extension" 错误
      deps: {
        inline: [/element-plus/, /@element-plus/],
      },
    },
  },
});
