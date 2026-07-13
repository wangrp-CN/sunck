# 涉铁工程智能监控平台 · 前端工程

基于 **Vite + Vue3 + TypeScript + Pinia + Vue Router + Element Plus** 的工程骨架（方案 A 原生服务）。

## 技术栈
- 构建：Vite 5
- 框架：Vue 3（`<script setup>` + TS）
- 状态：Pinia（`stores/auth.ts`）
- 路由：Vue Router 4（含 JWT 路由守卫，`router/index.ts`）
- UI：Element Plus + 图标
- 请求：Axios 封装（`utils/request.ts`，自动注入 JWT、统一解包 `ApiResponse`、401 跳登录）

## 目录
```
src/
  api/        接口封装（auth.ts）
  stores/     Pinia 状态（auth.ts）
  router/     路由与守卫
  layouts/    主框架布局（侧边栏 + 顶栏）
  views/      页面（登录 / 大屏占位 / 404）
  utils/      Axios 封装
  types/      全局类型
```

## 开发
```bash
npm install
npm run dev        # http://localhost:5173 ，/api 代理到后端 8000
npm run build      # 产物输出 dist/
npm run type-check # vue-tsc 类型检查
```

## 与后端联调
开发时 Vite 已将 `/api` 代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`）。
生产部署将 `dist/` 交由 Nginx 托管，并将 `/api` 反向代理到 FastAPI。

> 默认管理员：admin / Admin@123456
