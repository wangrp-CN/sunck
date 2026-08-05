<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  fetchSystemLogs,
  fetchSystemLogMeta,
  exportSystemLogs,
  type SystemLogItem,
} from "@/api/log";
import { exportAuditLogs } from "@/api/audit";
import TablePager from "@/components/TablePager.vue";

// 日志类型切换：audit=操作日志, system=系统日志
const logType = ref<"audit" | "system">("audit");

// 系统日志状态
const loading = ref(false);
const tableData = ref<SystemLogItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);

// 筛选条件（共用）
const startDate = ref("");
const endDate = ref("");

// 系统日志筛选
const sysLevel = ref<string | null>(null);
const sysModule = ref<string | null>(null);
const sysKeyword = ref("");
const sysLevels = ref<string[]>([]);
const sysModules = ref<string[]>([]);

// 操作日志状态 - 复用 AuditLogView 的模式，但在此视图中用简化的内联实现
import { fetchAuditLogs, fetchAuditMeta, type AuditLogItem } from "@/api/audit";
const auditLoading = ref(false);
const auditData = ref<AuditLogItem[]>([]);
const auditTotal = ref(0);
const auditPage = ref(1);
const auditSize = ref(10);
const auditModule = ref("");
const auditAction = ref("");
const auditUsername = ref("");
const auditModules = ref<string[]>([]);
const auditActions = ref<string[]>([]);

function levelColor(level: string): string {
  switch (level) {
    case "DEBUG": return "info";
    case "INFO": return "";
    case "WARNING": return "warning";
    case "ERROR": return "danger";
    case "CRITICAL": return "danger";
    default: return "info";
  }
}

// ── 系统日志操作 ──
async function loadSystemLogs() {
  loading.value = true;
  try {
    const pageData = await fetchSystemLogs({
      page: page.value,
      size: size.value,
      level: sysLevel.value ?? undefined,
      module: sysModule.value ?? undefined,
      keyword: sysKeyword.value || undefined,
      start: startDate.value || undefined,
      end: endDate.value || undefined,
    });
    tableData.value = pageData.items;
    total.value = pageData.total;
  } catch {
    // 拦截器统一提示
  } finally {
    loading.value = false;
  }
}

async function loadSysMeta() {
  try {
    const meta = await fetchSystemLogMeta();
    sysLevels.value = meta.levels;
    sysModules.value = meta.modules;
  } catch {
    // 可忽略
  }
}

function handleSysSearch() {
  page.value = 1;
  loadSystemLogs();
}

function handleSysReset() {
  sysLevel.value = null;
  sysModule.value = null;
  sysKeyword.value = "";
  startDate.value = "";
  endDate.value = "";
  page.value = 1;
  loadSystemLogs();
}

function handleSysExport() {
  exportSystemLogs({
    level: sysLevel.value ?? undefined,
    module: sysModule.value ?? undefined,
    keyword: sysKeyword.value || undefined,
    start: startDate.value || undefined,
    end: endDate.value || undefined,
  });
  ElMessage.success("正在下载系统日志 CSV...");
}

// ── 操作日志操作 ──
async function loadAuditLogs() {
  auditLoading.value = true;
  try {
    const pageData = await fetchAuditLogs({
      page: auditPage.value,
      size: auditSize.value,
      module: auditModule.value || undefined,
      action: auditAction.value || undefined,
      username: auditUsername.value || undefined,
      start: startDate.value || undefined,
      end: endDate.value || undefined,
    });
    auditData.value = pageData.items;
    auditTotal.value = pageData.total;
  } catch {
    // 拦截器统一提示
  } finally {
    auditLoading.value = false;
  }
}

async function loadAuditMeta() {
  try {
    const meta = await fetchAuditMeta();
    auditModules.value = meta.modules;
    auditActions.value = meta.actions;
  } catch {
    // 可忽略
  }
}

function handleAuditSearch() {
  auditPage.value = 1;
  loadAuditLogs();
}

function handleAuditReset() {
  auditModule.value = "";
  auditAction.value = "";
  auditUsername.value = "";
  startDate.value = "";
  endDate.value = "";
  auditPage.value = 1;
  loadAuditLogs();
}

function handleAuditExport() {
  exportAuditLogs({
    module: auditModule.value || undefined,
    action: auditAction.value || undefined,
    username: auditUsername.value || undefined,
    start: startDate.value || undefined,
    end: endDate.value || undefined,
  });
  ElMessage.success("正在下载操作日志 CSV...");
}

// 切换日志类型时重新加载
function onTypeChange() {
  if (logType.value === "audit") {
    loadAuditLogs();
  } else {
    loadSystemLogs();
  }
}

// ── 行详情弹窗 ──
const detailVisible = ref(false);
const detailContent = ref("");

function showDetail(row: SystemLogItem) {
  detailContent.value = [
    `级别: ${row.level}`,
    `模块: ${row.module}`,
    `摘要: ${row.message}`,
    `来源: ${row.source || "—"}`,
    `关联用户: ${row.user_id || "—"}`,
    `时间: ${row.created_at || "—"}`,
    "",
    "详细上下文:",
    row.detail || "（无）",
    row.traceback ? `\n异常堆栈:\n${row.traceback}` : "",
  ].join("\n");
  detailVisible.value = true;
}

onMounted(() => {
  loadAuditLogs();
  loadAuditMeta();
  loadSysMeta();
});
</script>

<template>
  <div class="page">
    <h2 class="page-title">日志管理</h2>

    <!-- 类型切换 -->
    <el-tabs v-model="logType" @tab-change="onTypeChange">
      <!-- ═══ 操作日志 ═══ -->
      <el-tab-pane label="操作日志" name="audit">
        <div class="tool-bar">
          <el-select
            v-model="auditModule"
            placeholder="模块"
            clearable
            class="filter-select"
            @change="handleAuditSearch"
          >
            <el-option v-for="m in auditModules" :key="m" :label="m" :value="m" />
          </el-select>
          <el-select
            v-model="auditAction"
            placeholder="动作"
            clearable
            class="filter-select"
            @change="handleAuditSearch"
          >
            <el-option v-for="a in auditActions" :key="a" :label="a" :value="a" />
          </el-select>
          <el-input
            v-model="auditUsername"
            placeholder="操作人"
            clearable
            class="search-input"
            @keyup.enter="handleAuditSearch"
            @clear="handleAuditSearch"
          />
          <el-date-picker
            v-model="startDate"
            type="date"
            placeholder="起始日期"
            value-format="YYYY-MM-DD"
            class="date-picker"
          />
          <el-date-picker
            v-model="endDate"
            type="date"
            placeholder="结束日期"
            value-format="YYYY-MM-DD"
            class="date-picker"
          />
          <el-button type="primary" @click="handleAuditSearch">搜索</el-button>
          <el-button @click="handleAuditReset">重置</el-button>
          <el-button type="success" @click="handleAuditExport">导出 CSV</el-button>
        </div>

        <el-table v-loading="auditLoading" :data="auditData" border stripe row-key="id">
          <el-table-column label="序号" width="64" align="center">
            <template #default="{ $index }">{{ (auditPage - 1) * auditSize + $index + 1 }}</template>
          </el-table-column>
          <el-table-column prop="username" label="操作人" width="100" />
          <el-table-column prop="module" label="模块" width="100" />
          <el-table-column label="动作" width="80">
            <template #default="{ row }">
              <el-tag size="small">{{ row.action }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="method" label="方法" width="70" />
          <el-table-column prop="path" label="路径" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态码" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status_code < 400 ? 'success' : 'danger'" size="small">
                {{ row.status_code }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="ip" label="IP" width="130" />
          <el-table-column prop="created_at" label="时间" width="170" />
        </el-table>

        <div class="pager">
          <TablePager
            v-model:page="auditPage"
            v-model:size="auditSize"
            :total="auditTotal"
            @change="loadAuditLogs"
          />
        </div>
      </el-tab-pane>

      <!-- ═══ 系统日志 ═══ -->
      <el-tab-pane label="系统日志" name="system">
        <div class="tool-bar">
          <el-select
            v-model="sysLevel"
            placeholder="级别"
            clearable
            class="filter-select"
            @change="handleSysSearch"
          >
            <el-option v-for="l in sysLevels" :key="l" :label="l" :value="l" />
          </el-select>
          <el-select
            v-model="sysModule"
            placeholder="模块"
            clearable
            class="filter-select"
            @change="handleSysSearch"
          >
            <el-option v-for="m in sysModules" :key="m" :label="m" :value="m" />
          </el-select>
          <el-input
            v-model="sysKeyword"
            placeholder="关键词搜索"
            clearable
            class="search-input"
            @keyup.enter="handleSysSearch"
            @clear="handleSysSearch"
          />
          <el-date-picker
            v-model="startDate"
            type="date"
            placeholder="起始日期"
            value-format="YYYY-MM-DD"
            class="date-picker"
            @change="handleSysSearch"
          />
          <el-date-picker
            v-model="endDate"
            type="date"
            placeholder="结束日期"
            value-format="YYYY-MM-DD"
            class="date-picker"
            @change="handleSysSearch"
          />
          <el-button type="primary" @click="handleSysSearch">搜索</el-button>
          <el-button @click="handleSysReset">重置</el-button>
          <el-button type="success" @click="handleSysExport">导出 CSV</el-button>
        </div>

        <el-table v-loading="loading" :data="tableData" border stripe row-key="id">
          <el-table-column label="序号" width="64" align="center">
            <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
          </el-table-column>
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag :type="levelColor(row.level)" size="small" effect="dark">
                {{ row.level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="module" label="模块" width="100" />
          <el-table-column prop="message" label="摘要" min-width="200" show-overflow-tooltip />
          <el-table-column prop="source" label="来源" width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="showDetail(row)">
                详情
              </el-button>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="170" />
        </el-table>

        <div class="pager">
          <TablePager
            v-model:page="page"
            v-model:size="size"
            :total="total"
            @change="loadSystemLogs"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="日志详情" width="600px">
      <pre class="detail-pre">{{ detailContent }}</pre>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 4px;
}
.page-title {
  margin: 0 0 14px 0;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.tool-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  align-items: center;
}
.search-input {
  width: 180px;
}
.filter-select {
  width: 130px;
}
.date-picker {
  width: 150px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.detail-pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 13px;
  line-height: 1.6;
  background: #f5f7fa;
  padding: 14px;
  border-radius: 6px;
  max-height: 400px;
  overflow-y: auto;
}
</style>
