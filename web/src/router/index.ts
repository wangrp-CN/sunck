import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
} from "vue-router";
import { getToken } from "@/utils/request";
import DefaultLayout from "@/layouts/DefaultLayout.vue";

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/",
    component: DefaultLayout,
    redirect: "/dashboard",
    children: [
      {
        path: "dashboard",
        name: "dashboard",
        component: () => import("@/views/DashboardView.vue"),
        meta: { title: "监控大屏" },
      },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("@/views/NotFoundView.vue"),
    meta: { public: true, title: "页面不存在" },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// 全局前置守卫：未登录跳登录页
router.beforeEach((to) => {
  const loggedIn = Boolean(getToken());
  if (!to.meta.public && !loggedIn) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && loggedIn) {
    return { name: "dashboard" };
  }
  return true;
});

export default router;
