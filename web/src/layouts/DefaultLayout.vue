<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  DataLine,
  Position,
  Folder,
  Cpu,
  User,
  Setting,
  Location,
  Notebook,
  Warning,
  Bell,
  Monitor,
  Compass,
  VideoCamera,
  TrendCharts,
} from "@element-plus/icons-vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import {
  fetchNotifications,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/api/notification";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const activeMenu = computed(() => route.path);

const nickname = computed(() => auth.user?.nickname || auth.user?.username || "未登录");

async function handleLogout() {
  await auth.logout();
  ElMessage.success("已退出登录");
  router.push({ name: "login" });
}

// ---------------------------------------------------------------------------
// 通知中心：铃铛 + 未读角标 + 抽屉，定时轮询未读数
// ---------------------------------------------------------------------------
const notifVisible = ref(false);
const notifLoading = ref(false);
const notifList = ref<NotificationItem[]>([]);
const notifUnread = ref(0);
const notifTotal = ref(0);
const notifPage = ref(1);
const notifSize = ref(20);
const notifTab = ref<"all" | "unread">("all");

const CATEGORY_META: Record<string, { label: string; type: "" | "danger" | "warning" | "info" | "success" }> = {
  alarm: { label: "告警", type: "danger" },
  hazard: { label: "隐患", type: "warning" },
  system: { label: "系统", type: "info" },
  other: { label: "其他", type: "" },
};
function categoryMeta(c: string) {
  return CATEGORY_META[c] || CATEGORY_META.other;
}

// YYYY-MM-DDTHH:mm:ss → MM-DD HH:mm（北京墙钟直读）
function fmtTime(ts: string | null): string {
  if (!ts) return "";
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (m) return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
  return ts;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

async function refreshUnread() {
  if (!auth.user) return;
  try {
    const r = await fetchUnreadCount();
    notifUnread.value = r.count;
  } catch {
    /* 轮询失败静默 */
  }
}

async function loadNotifList() {
  if (!auth.user) return;
  notifLoading.value = true;
  try {
    const res = await fetchNotifications({
      page: notifPage.value,
      size: notifSize.value,
      unread_only: notifTab.value === "unread",
    });
    notifList.value = res.items;
    notifTotal.value = res.total;
    notifUnread.value = res.unread;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载通知失败");
  } finally {
    notifLoading.value = false;
  }
}

function openNotif() {
  notifPage.value = 1;
  notifTab.value = "all";
  notifVisible.value = true;
  loadNotifList();
}

async function onNotifTabChange() {
  notifPage.value = 1;
  await loadNotifList();
}

async function onNotifPageChange(p: number) {
  notifPage.value = p;
  await loadNotifList();
}

async function markRead(item: NotificationItem) {
  if (item.is_read) return;
  try {
    await markNotificationRead(item.id);
    item.is_read = true;
    notifUnread.value = Math.max(0, notifUnread.value - 1);
  } catch (e: any) {
    ElMessage.error(e?.message || "标记已读失败");
  }
}

async function markAllRead() {
  try {
    const res = await markAllNotificationsRead();
    ElMessage.success(`已标记 ${res.updated} 条为已读`);
    notifList.value.forEach((n) => (n.is_read = true));
    notifUnread.value = 0;
  } catch (e: any) {
    ElMessage.error(e?.message || "全部已读失败");
  }
}

// 点击通知：有 link 则跳转，否则标记已读
function onNotifClick(item: NotificationItem) {
  if (item.link) {
    router.push(item.link);
    notifVisible.value = false;
    if (!item.is_read) markRead(item);
    return;
  }
  markRead(item);
}

// 跳转到独立消息中心页
function goAllNotif() {
  notifVisible.value = false;
  router.push({ name: "notifications" });
}

onMounted(() => {
  refreshUnread();
  // 每 30s 轮询未读数量（轻量接口）
  pollTimer = setInterval(refreshUnread, 30000);
});
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">涉铁监控平台</div>
      <el-menu :default-active="activeMenu" router class="menu">
        <el-menu-item index="/dashboard">
          <el-icon><DataLine /></el-icon>
          <span>监控大屏</span>
        </el-menu-item>
        <el-menu-item index="/realtime">
          <el-icon><Position /></el-icon>
          <span>实时监控</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目管理</span>
        </el-menu-item>
        <el-menu-item index="/projects/compare">
          <el-icon><TrendCharts /></el-icon>
          <span>对比大屏</span>
        </el-menu-item>
        <el-sub-menu index="/devices-group">
          <template #title>
            <el-icon><Cpu /></el-icon>
            <span>设备管理</span>
          </template>
          <el-menu-item index="/devices">设备列表</el-menu-item>
          <el-menu-item index="/devices/online">在线看板</el-menu-item>
          <el-menu-item index="/devices/health">
            <el-icon><Monitor /></el-icon>
            <span>设备健康</span>
          </el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/persons">
          <el-icon><User /></el-icon>
          <span>人员管理</span>
        </el-menu-item>
        <el-menu-item index="/machines">
          <el-icon><Setting /></el-icon>
          <span>机械管理</span>
        </el-menu-item>
        <el-menu-item index="/fences">
          <el-icon><Location /></el-icon>
          <span>电子围栏</span>
        </el-menu-item>
        <el-menu-item index="/jobs">
          <el-icon><Notebook /></el-icon>
          <span>作业计划</span>
        </el-menu-item>
        <el-menu-item index="/inspections">
          <el-icon><Compass /></el-icon>
          <span>巡检打卡</span>
        </el-menu-item>
        <el-menu-item index="/videos">
          <el-icon><VideoCamera /></el-icon>
          <span>视频AI</span>
        </el-menu-item>
        <el-menu-item index="/alarms">
          <el-icon><Warning /></el-icon>
          <span>告警管理</span>
        </el-menu-item>
        <el-menu-item index="/hazards">
          <el-icon><Bell /></el-icon>
          <span>隐患治理</span>
        </el-menu-item>
        <el-menu-item index="/notifications">
          <el-icon><Bell /></el-icon>
          <span>消息中心</span>
        </el-menu-item>
        <el-menu-item index="/audit-logs">
          <el-icon><Document /></el-icon>
          <span>操作审计</span>
        </el-menu-item>
        <el-sub-menu index="/system">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统管理</span>
          </template>
          <el-menu-item index="/system/users">用户管理</el-menu-item>
          <el-menu-item index="/system/roles">角色管理</el-menu-item>
          <el-menu-item index="/system/departments">部门管理</el-menu-item>
          <el-menu-item index="/dicts">数据字典</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="title">{{ (route.meta.title as string) || "控制台" }}</span>
        <div class="user">
          <el-badge :value="notifUnread" :hidden="notifUnread === 0" :max="99" class="notif-badge">
            <el-button text circle @click="openNotif">
              <el-icon :size="20"><Bell /></el-icon>
            </el-button>
          </el-badge>
          <span class="nickname">{{ nickname }}</span>
          <el-button text type="primary" @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 通知中心抽屉 -->
    <el-drawer v-model="notifVisible" title="通知中心" direction="rtl" size="380px">
      <div class="notif-head">
        <el-radio-group v-model="notifTab" size="small" @change="onNotifTabChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="unread">未读 ({{ notifUnread }})</el-radio-button>
        </el-radio-group>
        <el-button
          v-if="notifUnread > 0"
          link
          type="primary"
          size="small"
          @click="markAllRead"
        >
          全部已读
        </el-button>
      </div>
      <el-scrollbar v-loading="notifLoading" class="notif-scroll">
        <div v-if="notifList.length === 0" class="notif-empty">暂无通知</div>
        <div
          v-for="item in notifList"
          :key="item.id"
          class="notif-item"
          :class="{ unread: !item.is_read }"
          @click="onNotifClick(item)"
        >
          <div class="notif-row">
            <el-tag :type="categoryMeta(item.category).type" size="small" effect="light">
              {{ categoryMeta(item.category).label }}
            </el-tag>
            <span class="notif-title">{{ item.title }}</span>
            <span v-if="!item.is_read" class="notif-dot" />
          </div>
          <div v-if="item.content" class="notif-content">{{ item.content }}</div>
          <div class="notif-foot">
            <span class="notif-time">{{ fmtTime(item.created_at) }}</span>
            <el-button
              v-if="!item.is_read"
              link
              type="primary"
              size="small"
              @click.stop="markRead(item)"
            >
              标记已读
            </el-button>
          </div>
        </div>
      </el-scrollbar>
      <div v-if="notifTotal > notifSize" class="notif-pager">
        <el-pagination
          v-model:current-page="notifPage"
          :total="notifTotal"
          :page-size="notifSize"
          layout="prev, pager, next"
          background
          small
          @current-change="onNotifPageChange"
        />
      </div>
      <div class="notif-footer">
        <el-button text type="primary" size="small" @click="goAllNotif">
          查看全部通知
        </el-button>
      </div>
    </el-drawer>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #001529;
  color: #fff;
}
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  color: #fff;
}
.menu {
  border-right: none;
  background: #001529;
}
.menu :deep(.el-menu-item) {
  color: #c0c4cc;
}
.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #1890ff;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #eee;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.user {
  display: flex;
  align-items: center;
  gap: 12px;
}
.notif-badge {
  margin-right: 4px;
}
.nickname {
  color: #606266;
}
.main {
  background: #f0f2f5;
}

/* 通知抽屉 */
.notif-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.notif-scroll {
  height: calc(100vh - 180px);
}
.notif-empty {
  color: #909399;
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}
.notif-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.notif-item:hover {
  background: #f5f7fa;
}
.notif-item.unread {
  background: #f0f7ff;
  border-color: #c6e2ff;
}
.notif-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.notif-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notif-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f56c6c;
  flex-shrink: 0;
}
.notif-content {
  font-size: 12px;
  color: #606266;
  margin-top: 6px;
  line-height: 1.5;
  word-break: break-all;
}
.notif-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.notif-time {
  font-size: 12px;
  color: #909399;
}
.notif-pager {
  margin-top: 8px;
  display: flex;
  justify-content: center;
}
.notif-footer {
  margin-top: 8px;
  display: flex;
  justify-content: center;
  border-top: 1px solid #ebeef5;
  padding-top: 8px;
}
</style>
