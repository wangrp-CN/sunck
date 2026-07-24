<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import { fetchDeviceHealth } from "@/api/device";
import { fetchProjects } from "@/api/project";
import { DEVICE_TYPE_LABELS } from "@/api/realtime";
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
function healthTag(score: number): "" | "success" | "warning" | "danger" {
  if (score >= 80) return "success";
  if (score >= 40) return "warning";
  return "danger";
}
function healthText(score: number): string {
  if (score >= 80) return "良好";
  if (score >= 40) return "关注";
  return "告警";
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
    >
      <el-table-column prop="device_no" label="设备编号" width="150" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">{{ row.type_label }}</template>
      </el-table-column>
      <el-table-column label="项目" min-width="130">
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="在线" width="80">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'danger'" size="small">
            {{ row.online ? "在线" : "离线" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_report_time" label="最近上报" min-width="150" />
      <el-table-column prop="report_count" label="窗口上报" width="100" />
      <el-table-column prop="alarm_count" label="窗口告警" width="100" />
      <el-table-column label="健康分" width="160">
        <template #default="{ row }">
          <el-progress
            :percentage="row.health_score"
            :status="row.health_score >= 80 ? 'success' : row.health_score >= 40 ? 'warning' : 'exception'"
          />
          <span class="health-text" :class="healthTag(row.health_score)">
            {{ healthText(row.health_score) }}
          </span>
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
.health-text { font-size: 12px; margin-left: 6px; }
</style>
