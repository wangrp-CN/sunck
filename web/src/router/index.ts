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
        redirect: "/projects/list",
        meta: { title: "项目管理" },
        children: [
          {
            path: "list",
            name: "projects-list",
            component: () => import("@/views/ProjectListView.vue"),
            meta: { title: "项目列表" },
          },
        ],
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
        path: "devices/commands",
        name: "devices-commands",
        component: () => import("@/views/CommandView.vue"),
        meta: { title: "指令下发记录" },
      },
      {
        path: "devices/locate",
        name: "devices-locate",
        component: () => import("@/views/LocateDeviceListView.vue"),
        meta: { title: "人机定位设备列表" },
      },
      {
        path: "devices/anti-intrusion",
        name: "devices-anti-intrusion",
        component: () => import("@/views/AntiIntrusionDeviceListView.vue"),
        meta: { title: "大机防侵限设备列表" },
      },
      {
        path: "devices/train-approach",
        name: "devices-train-approach",
        component: () => import("@/views/TrainApproachDeviceListView.vue"),
        meta: { title: "列车接近报警设备列表" },
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
        // 电子围栏管理：一级为目录（不渲染页面），子菜单「电子围栏列表」承载列表页，
        // 与项目管理 /projects → /projects/list 的层级约定保持一致。
        path: "fences",
        name: "fences",
        redirect: "/fences/list",
        meta: { title: "电子围栏管理" },
        children: [
          {
            path: "list",
            name: "fences-list",
            component: () => import("@/views/FenceListView.vue"),
            meta: { title: "电子围栏列表" },
          },
        ],
      },
      {
        path: "jobs",
        name: "jobs",
        component: () => import("@/views/JobView.vue"),
        meta: { title: "作业计划" },
      },
      {
        path: "inspections",
        name: "inspections",
        component: () => import("@/views/InspectionView.vue"),
        meta: { title: "巡检打卡" },
      },
      {
        path: "videos",
        name: "videos",
        component: () => import("@/views/VideoView.vue"),
        meta: { title: "视频AI" },
      },
      {
        path: "devices/health",
        name: "devices-health",
        component: () => import("@/views/DeviceHealthView.vue"),
        meta: { title: "设备健康" },
      },
      {
        path: "projects/detail",
        name: "project-detail-entry",
        component: () => import("@/views/ProjectDetailView.vue"),
        meta: { title: "项目详情" },
      },
      {
        path: "projects/:id/detail",
        name: "project-detail",
        component: () => import("@/views/ProjectDetailView.vue"),
        meta: { title: "项目详情" },
      },
      {
        path: "intelligence/correlation",
        name: "intelligence-correlation",
        component: () => import("@/views/AlarmCorrelationView.vue"),
        meta: { title: "跨设备根因关联" },
      },
      {
        path: "intelligence/correlation-compare",
        name: "intelligence-correlation-compare",
        component: () => import("@/views/CorrelationCompareView.vue"),
        meta: { title: "关联热力对比" },
      },
      {
        path: "intelligence/threshold",
        name: "intelligence-threshold",
        component: () => import("@/views/ThresholdAutoLearningView.vue"),
        meta: { title: "阈值自学习" },
      },
      {
        path: "intelligence/subscriptions",
        name: "intelligence-subscriptions",
        component: () => import("@/views/SubscriptionView.vue"),
        meta: { title: "报告订阅" },
      },
      {
        path: "intelligence/report-center",
        name: "intelligence-report-center",
        component: () => import("@/views/ReportCenterView.vue"),
        meta: { title: "报表中心" },
      },
      {
        path: "alarms",
        name: "alarms",
        component: () => import("@/views/AlarmView.vue"),
        meta: { title: "告警管理" },
      },
      // 告警详情页（大屏子菜单）：无 id 入口供菜单直达，进入后定位最新待处理
      // 告警并 replace 到带 id 路由；两条路由复用同一组件。
      // 注意 "alarms/detail" 必须在 "alarms/:id/detail" 之前，否则会被当作 id。
      {
        path: "alarms/detail",
        name: "alarm-detail-entry",
        component: () => import("@/views/AlarmDetailView.vue"),
        meta: { title: "告警详情" },
      },
      {
        path: "alarms/:id/detail",
        name: "alarm-detail",
        component: () => import("@/views/AlarmDetailView.vue"),
        meta: { title: "告警详情" },
      },
      {
        path: "dispatch",
        name: "dispatch",
        component: () => import("@/views/DispatchView.vue"),
        meta: { title: "根因派单" },
      },
      {
        path: "duty-roster",
        name: "duty-roster",
        component: () => import("@/views/DutyRosterView.vue"),
        meta: { title: "值班排班" },
      },
      {
        path: "alarm-policies",
        name: "alarm-policies",
        component: () => import("@/views/AlarmPolicyView.vue"),
        meta: { title: "告警策略" },
      },
      {
        path: "playbooks",
        name: "playbooks",
        component: () => import("@/views/PlaybookView.vue"),
        meta: { title: "处置预案" },
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
        path: "dicts",
        name: "dicts",
        component: () => import("@/views/DictView.vue"),
        meta: { title: "数据字典" },
      },
      {
        path: "maps",
        name: "maps",
        component: () => import("@/views/MapManageView.vue"),
        meta: { title: "地图资源库" },
      },
      {
        path: "maps/draw",
        name: "maps-draw",
        component: () => import("@/views/MapDrawView.vue"),
        meta: { title: "手动绘制" },
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
      {
        path: "system/menus",
        name: "system-menus",
        component: () => import("@/views/SystemMenuView.vue"),
        meta: { title: "菜单管理" },
      },
      {
        path: "system/logs",
        name: "system-logs",
        component: () => import("@/views/SystemLogView.vue"),
        meta: { title: "日志管理" },
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
