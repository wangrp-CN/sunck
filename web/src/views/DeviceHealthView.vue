<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import { fetchDeviceHealth } from "@/api/device";
import { fetchProjects } from "@/api/project";
import { getHealthTrend } from "@/api/metrics";
import { DEVICE_TYPE_LABELS } from "@/api/realtime";
import TrendLine from "@/components/TrendLine.vue";
import type { DeviceHealthResp, Project } from "@/types";

const auth = useAuthStore();

const projects = ref<Project[]>([]);
const resp = ref<DeviceHealthResp | null>(null);
const loading = ref(false);
const filters = reactive({
  device_type: "" as string,
  project_id: null as number | null,
  hours: 24,
});

const deviceTypeOptions = computed(() =>
  Object.entries(DEVICE_TYPE_LABELS).map(([v, l]) => ({ value: v, label: l })),
);

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* ignore */
  }
}
async function load() {
  loading.value = true;
  try {
    resp.value = await fetchDeviceHealth({
      device_type: filters.device_type || undefined,
      project_id: filters.project_id ?? undefined,
      hours: filters.hours,
    });
  } catch (e: any) {
    ElMessage.error(e?.message || "加载设备健康失败");
  } finally {
    loading.value = false;
  }
}
function projectName(id?: number | null) {
  if (id == null) return "—";
  return projects.value.find((p) => p.id === id)?.name ?? `ID:${id}`;
}
// 健康分档：直接采用后端 health_level（优/良/中/差），不再用前端阈值复算
function healthLevelTag(level?: string | null): "" | "success" | "primary" | "warning" | "danger" {
  switch (level) {
    case "优":
      return "success";
    case "良":
      return "primary";
    case "中":
      return "warning";
    case "差":
      return "danger";
    default:
      return "";
  }
}
// 进度条状态（优=绿 良=蓝 中=橙 差=红）
function healthLevelStatus(level?: string | null): "" | "success" | "warning" | "exception" {
  switch (level) {
    case "优":
      return "success";
    case "中":
      return "warning";
    case "差":
      return "exception";
    default:
      return "";
  }
}
function onlineStateText(state?: string | null): string {
  switch (state) {
    case "fresh":
      return "新鲜";
    case "stale":
      return "陈旧";
    case "offline":
      return "离线";
    default:
      return "—";
  }
}

// 健康分趋势 sparkline：仅在该设备被展开时懒加载近 30 天健康分序列
const healthTrend = ref<Record<string, { t: string; v: number }[]>>({});
const healthTrendLoading = ref<Set<string>>(new Set());

function healthColor(level?: string | null): string {
  switch (level) {
    case "优":
      return "#67c23a";
    case "良":
      return "#409eff";
    case "中":
      return "#e6a23c";
    default:
      return "#f56c6c";
  }
}

async function onExpand(row: any, expandedRows: any[]) {
  const no = row.device_no as string;
  const isOpen = expandedRows.some((r) => r.device_no === no);
  if (!isOpen || healthTrend.value[no]) return;
  healthTrendLoading.value = new Set(healthTrendLoading.value).add(no);
  try {
    const res = await getHealthTrend(no, 30);
    healthTrend.value = {
      ...healthTrend.value,
      [no]: (res.series || []).map((s) => ({ t: s.snapshot_at, v: s.health_score })),
    };
  } catch {
    /* 拦截器已提示，静默避免影响主表 */
  } finally {
    const next = new Set(healthTrendLoading.value);
    next.delete(no);
    healthTrendLoading.value = next;
  }
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* ignore */
    }
  }
  await loadProjects();
  await load();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <el-form :inline="true" class="filters">
        <el-form-item label="设备类型">
          <el-select v-model="filters.device_type" placeholder="全部" clearable style="width: 150px">
            <el-option v-for="o in deviceTypeOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目">
          <el-select v-model="filters.project_id" placeholder="全部" clearable style="width: 160px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="窗口(小时)">
          <el-input-number v-model="filters.hours" :min="1" :max="720" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="load">查询</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="summary" v-if="resp">
      <el-card shadow="never" class="sum-card">
        <div class="sum-num">{{ resp.total }}</div>
        <div class="sum-label">设备总数</div>
      </el-card>
      <el-card shadow="never" class="sum-card">
        <div class="sum-num online">{{ resp.online }}</div>
        <div class="sum-label">在线</div>
      </el-card>
      <el-card shadow="never" class="sum-card">
        <div class="sum-num offline">{{ resp.offline }}</div>
        <div class="sum-label">离线</div>
      </el-card>
      <el-card shadow="never" class="sum-card">
        <div class="sum-num">{{ resp.threshold_seconds }}s</div>
        <div class="sum-label">在线阈值</div>
      </el-card>
    </div>

    <el-table
      :data="resp?.items || []"
      v-loading="loading"
      border
      stripe
      style="width: 100%"
      @expand-change="onExpand"
    >
      <el-table-column type="expand" width="40">
        <template #default="{ row }">
          <div class="health-trend">
            <div class="health-trend-head">
              <span>近 30 天健康分趋势</span>
              <span class="muted">设备 {{ row.device_no }}</span>
            </div>
            <TrendLine
              v-if="(healthTrend[row.device_no] || []).length"
              :points="healthTrend[row.device_no]"
              :color="healthColor(row.health_level)"
              :height="72"
              :width="460"
            />
            <span v-else-if="healthTrendLoading.has(row.device_no)" class="muted">
              加载趋势中…
            </span>
            <span v-else class="muted">暂无快照数据</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="device_no" label="设备编号" width="150" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">{{ row.type_label }}</template>
      </el-table-column>
      <el-table-column label="项目" min-width="130">
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="在线" width="110">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'danger'" size="small">
            {{ row.online ? "在线" : "离线" }}
          </el-tag>
          <el-tag :type="row.online ? 'info' : 'danger'" size="small" style="margin-left: 4px">
            {{ onlineStateText(row.online_state) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_report_time" label="最近上报" min-width="150" />
      <el-table-column prop="report_count" label="窗口上报" width="100" />
      <el-table-column prop="alarm_count" label="窗口告警" width="100" />
      <el-table-column label="健康分" min-width="190">
        <template #default="{ row }">
          <el-progress
            :percentage="row.health_score"
            :status="healthLevelStatus(row.health_level)"
          />
          <el-tag :type="healthLevelTag(row.health_level)" size="small" style="margin-left: 6px">
            {{ row.health_level || "—" }}
          </el-tag>
        </template>
      </el-table-column>
      <template #empty>暂无设备</template>
    </el-table>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { margin-bottom: 12px; }
.filters { flex-wrap: wrap; }
.summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }
.sum-card { text-align: center; }
.sum-num { font-size: 24px; font-weight: 700; color: #303133; }
.sum-num.online { color: #67c23a; }
.sum-num.offline { color: #f56c6c; }
.sum-label { font-size: 13px; color: #909399; margin-top: 4px; }
.health-trend { padding: 8px 12px; }
.health-trend-head { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px; color: #606266; }
.muted { color: #c0c4cc; font-size: 12px; }
</style>
