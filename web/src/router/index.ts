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
      {
        path: "realtime",
        name: "realtime",
        component: () => import("@/views/RealtimeView.vue"),
        meta: { title: "实时监控" },
      },
      {
        path: "track",
        name: "track",
        component: () => import("@/views/TrackView.vue"),
        meta: { title: "轨迹回放" },
      },
      {
        path: "projects",
        name: "projects",
        component: () => import("@/views/ProjectView.vue"),
        meta: { title: "项目管理" },
      },
      {
        path: "devices",
        name: "devices",
        component: () => import("@/views/DeviceView.vue"),
        meta: { title: "设备管理" },
      },
      {
        path: "devices/online",
        name: "devices-online",
        component: () => import("@/views/DeviceOnlineView.vue"),
        meta: { title: "设备在线看板" },
      },
      {
        path: "persons",
        name: "persons",
        component: () => import("@/views/PersonView.vue"),
        meta: { title: "人员管理" },
      },
      {
        path: "machines",
        name: "machines",
        component: () => import("@/views/MachineView.vue"),
        meta: { title: "机械管理" },
      },
      {
        path: "fences",
        name: "fences",
        component: () => import("@/views/FenceView.vue"),
        meta: { title: "电子围栏" },
      },
      {
        path: "jobs",
        name: "jobs",
        component: () => import("@/views/JobView.vue"),
        meta: { title: "作业计划" },
      },
      {
        path: "alarms",
        name: "alarms",
        component: () => import("@/views/AlarmView.vue"),
        meta: { title: "告警管理" },
      },
      {
        path: "hazards",
        name: "hazards",
        component: () => import("@/views/HazardView.vue"),
        meta: { title: "隐患治理" },
      },
      {
        path: "notifications",
        name: "notifications",
        component: () => import("@/views/NotificationView.vue"),
        meta: { title: "消息中心" },
      },
      {
        path: "audit-logs",
        name: "audit-logs",
        component: () => import("@/views/AuditLogView.vue"),
        meta: { title: "操作审计" },
      },
      {
        path: "system/users",
        name: "system-users",
        component: () => import("@/views/SystemUserView.vue"),
        meta: { title: "用户管理" },
      },
      {
        path: "system/roles",
        name: "system-roles",
        component: () => import("@/views/SystemRoleView.vue"),
        meta: { title: "角色管理" },
      },
      {
        path: "system/departments",
        name: "system-departments",
        component: () => import("@/views/SystemDeptView.vue"),
        meta: { title: "部门管理" },
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
