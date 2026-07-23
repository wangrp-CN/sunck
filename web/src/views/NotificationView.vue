<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/api/notification";

const router = useRouter();

// 全部 / 未读 切换（映射到后端 unread_only）
const tab = ref<"all" | "unread">("all");
const loading = ref(false);
const list = ref<NotificationItem[]>([]);
const total = ref(0);
const unread = ref(0);
const page = ref(1);
const size = ref(20);

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

async function load() {
  loading.value = true;
  try {
    const res = await fetchNotifications({
      page: page.value,
      size: size.value,
      unread_only: tab.value === "unread",
    });
    list.value = res.items;
    total.value = res.total;
    unread.value = res.unread;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载通知失败");
  } finally {
    loading.value = false;
  }
}

function onTabChange() {
  page.value = 1;
  load();
}
function onPageChange(p: number) {
  page.value = p;
  load();
}
function onSizeChange(s: number) {
  size.value = s;
  page.value = 1;
  load();
}

async function markRead(item: NotificationItem) {
  if (item.is_read) return;
  try {
    await markNotificationRead(item.id);
    item.is_read = true;
    unread.value = Math.max(0, unread.value - 1);
  } catch (e: any) {
    ElMessage.error(e?.message || "标记已读失败");
  }
}

async function markAllRead() {
  if (unread.value === 0) return;
  try {
    const res = await markAllNotificationsRead();
    ElMessage.success(`已标记 ${res.updated} 条为已读`);
    list.value.forEach((n) => (n.is_read = true));
    unread.value = 0;
  } catch (e: any) {
    ElMessage.error(e?.message || "全部已读失败");
  }
}

// 点击行：有 link 则跳转并标记已读，否则仅标记已读
function onRowClick(item: NotificationItem) {
  if (item.link) {
    if (!item.is_read) markRead(item);
    router.push(item.link);
    return;
  }
  markRead(item);
}

const hasUnread = computed(() => unread.value > 0);

onMounted(load);
</script>

<template>
  <div class="page">
    <el-card shadow="never" class="toolbar">
      <div class="toolbar-left">
        <el-radio-group v-model="tab" size="default" @change="onTabChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="unread">未读 ({{ unread }})</el-radio-button>
        </el-radio-group>
        <span class="total">共 {{ total }} 条</span>
      </div>
      <div class="toolbar-right">
        <el-button :disabled="!hasUnread" type="primary" @click="markAllRead">
          全部已读
        </el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table
        v-loading="loading"
        :data="list"
        row-key="id"
        stripe
        height="calc(100vh - 220px)"
        @row-click="onRowClick"
      >
        <el-table-column label="类别" width="90">
          <template #default="{ row }">
            <el-tag :type="categoryMeta(row.category).type" size="small" effect="light">
              {{ categoryMeta(row.category).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="title" :class="{ unread: !row.is_read }">{{ row.title }}</span>
            <span v-if="!row.is_read" class="dot" />
          </template>
        </el-table-column>
        <el-table-column label="内容" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="content">{{ row.content || "—" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_read" type="info" size="small" effect="plain">已读</el-tag>
            <el-tag v-else type="danger" size="small" effect="light">未读</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="120">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.is_read"
              link
              type="primary"
              size="small"
              @click.stop="markRead(row)"
            >
              标记已读
            </el-button>
            <el-button
              v-if="row.link"
              link
              type="primary"
              size="small"
              @click.stop="onRowClick(row)"
            >
              查看
            </el-button>
            <span v-if="row.is_read && !row.link" class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 0;
}
.toolbar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.total {
  color: #909399;
  font-size: 13px;
}
.toolbar-right {
  display: flex;
  gap: 8px;
}
.title {
  font-weight: 600;
  color: #303133;
}
.title.unread {
  color: #303133;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f56c6c;
  margin-left: 6px;
  vertical-align: middle;
}
.content {
  color: #606266;
  font-size: 13px;
}
.muted {
  color: #c0c4cc;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
:deep(.el-table__row) {
  cursor: pointer;
}
</style>
