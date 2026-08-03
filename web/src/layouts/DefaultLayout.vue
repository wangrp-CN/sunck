<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useBreakpoint } from "@/composables/useBreakpoint";
import SideMenu from "@/components/SideMenu.vue";
import {
  fetchNotifications,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/api/notification";
import { Bell, Menu as MenuIcon, ArrowLeft, ArrowRight } from "@element-plus/icons-vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { isMobile } = useBreakpoint();

// 桌面侧栏折叠：窄桌面或用户手动收起时仅显示图标，提升可读性
const collapsed = ref(false);

// 移动端抽屉式侧栏（窄屏下替代固定侧栏）
const drawerVisible = ref(false);
function openDrawer() {
  drawerVisible.value = true;
}

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
    <el-aside v-show="!isMobile" :width="collapsed ? '64px' : '220px'" class="aside">
      <div v-if="!collapsed" class="logo">涉铁监控平台</div>
      <div v-else class="logo collapsed-logo">涉</div>
      <div class="menu-wrap">
        <SideMenu :collapse="collapsed" />
      </div>
      <button
        class="collapse-toggle"
        :title="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="collapsed = !collapsed"
      >
        <el-icon :size="16">
          <ArrowLeft v-if="!collapsed" />
          <ArrowRight v-else />
        </el-icon>
      </button>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-button v-if="isMobile" text class="hamburger" @click="openDrawer">
            <el-icon :size="20"><MenuIcon /></el-icon>
          </el-button>
          <span class="title">{{ (route.meta.title as string) || "控制台" }}</span>
        </div>
        <div class="user">
          <el-badge :value="notifUnread" :hidden="notifUnread === 0" :max="99" class="notif-badge">
            <el-button text circle @click="openNotif">
              <el-icon :size="20"><Bell /></el-icon>
            </el-button>
          </el-badge>
          <span class="nickname hide-mobile">{{ nickname }}</span>
          <el-button text type="primary" @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 移动端侧栏抽屉（窄屏下替代固定侧栏） -->
    <el-drawer
      v-model="drawerVisible"
      direction="ltr"
      size="220px"
      :with-header="false"
      class="mobile-menu-drawer"
    >
      <SideMenu @navigate="drawerVisible = false" />
    </el-drawer>

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
  background: #0d47a1;
  color: #fff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  color: #fff;
  flex-shrink: 0;
  letter-spacing: 1px;
}
.logo.collapsed-logo {
  font-size: 18px;
  letter-spacing: 0;
}
/* 菜单滚动容器：在 aside 内占据剩余高度，内部长列表独立滚动 */
.menu-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* 折叠切换：常驻底部，明确的可点击态 */
.collapse-toggle {
  flex-shrink: 0;
  height: 40px;
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(0, 0, 0, 0.18);
  color: #c0c4cc;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.collapse-toggle:hover {
  background: rgba(0, 0, 0, 0.3);
  color: #fff;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #eee;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hamburger {
  margin-left: -8px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
/* 窄屏：缩小主区域留白，避免内容过挤 */
@media (max-width: 960px) {
  .main {
    padding: 8px;
  }
  .header {
    padding: 0 10px;
  }
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
