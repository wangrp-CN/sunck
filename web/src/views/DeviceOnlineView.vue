<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Refresh } from "@element-plus/icons-vue";
import {
  fetchOnlineStatus,
  DEVICE_TYPE_LABELS,
  type DeviceType,
  type OnlineStatusItem,
  type OnlineStatusResult,
} from "@/api/realtime";
import { fetchProjects } from "@/api/project";
import MapPanel from "@/components/MapPanel.vue";
import type { MapDevice, Project } from "@/types";

const loading = ref(false);
const result = ref<OnlineStatusResult | null>(null);
const projectId = ref<number | null>(null);
const deviceType = ref<string | null>(null);
const projectMap = ref<Map<number, string>>(new Map());
const updatedAt = ref<string>("—");

// 轮询刷新间隔（15s）
const POLL_MS = 15000;
let timer: number | undefined;

const summary = computed(() => {
  const r = result.value;
  if (!r) return { total: 0, online: 0, offline: 0, threshold: 0, rate: 0 };
  const total = r.total || 0;
  const online = r.online || 0;
  const offline = total - online;
  return {
    total,
    online,
    offline,
    threshold: r.threshold_seconds || 0,
    rate: total ? Math.round((online / total) * 100) : 0,
  };
});

const byTypeList = computed(() => {
  const r = result.value;
  if (!r) return [];
  return Object.entries(r.by_type || {}).map(([type, v]) => ({
    type,
    label: DEVICE_TYPE_LABELS[type as DeviceType] || type,
    total: v.total || 0,
    online: v.online || 0,
    offline: v.offline || 0,
  }));
});

const items = computed<OnlineStatusItem[]>(() => result.value?.items ?? []);

// 地图打点：在线设备高亮（live=在线），离线设备以灰色静态点呈现
const mapDevices = computed<MapDevice[]>(() =>
  items.value
    .filter((i) => i.gcj02)
    .map((i) => ({
      device_no: i.device_no,
      name: i.device_name || i.device_no,
      device_type: i.device_type as DeviceType,
      lng: i.gcj02!.lng,
      lat: i.gcj02!.lat,
      status: i.status,
      live: i.online,
    })),
);

function projectName(id: number | null): string {
  if (id == null) return "—";
  return projectMap.value.get(id) ?? `ID:${id}`;
}

async function loadProjects() {
  try {
    const all: Project[] = [];
    let p = 1;
    while (p <= 10) {
      const pd = await fetchProjects({ page: p, size: 200 });
      all.push(...pd.items);
      if (all.length >= pd.total) break;
      p++;
    }
    const map = new Map<number, string>();
    all.forEach((pr) => map.set(pr.id, pr.name));
    projectMap.value = map;
  } catch {
    // 不影响主功能
  }
}

async function load() {
  loading.value = true;
  try {
    const params: { project_id?: number; device_type?: string } = {};
    if (projectId.value != null) params.project_id = projectId.value;
    if (deviceType.value) params.device_type = deviceType.value;
    result.value = await fetchOnlineStatus(params);
    updatedAt.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    // 拦截器统一提示
  } finally {
    loading.value = false;
  }
}

function startPolling() {
  stopPolling();
  timer = window.setInterval(load, POLL_MS);
}
function stopPolling() {
  if (timer) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

function fmtAge(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}m${r}s` : `${m}m`;
}
function fmtTime(s: string | null): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 19);
}
function typeLabel(t: string): string {
  return DEVICE_TYPE_LABELS[t as DeviceType] || t;
}

onMounted(async () => {
  await loadProjects();
  await load();
  startPolling();
});
onBeforeUnmount(stopPolling);
</script>

<template>
  <div class="online">
    <!-- 概览卡片 -->
    <el-row :gutter="12" class="cards">
      <el-col :span="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">设备总数</div>
          <div class="stat-value">{{ summary.total }}</div>
          <div class="stat-sub">已上报位置的设备</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat online-card">
          <div class="stat-label">在线</div>
          <div class="stat-value ok">{{ summary.online }}</div>
          <div class="stat-sub">在线率 {{ summary.rate }}%</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat offline-card">
          <div class="stat-label">离线</div>
          <div class="stat-value dim">{{ summary.offline }}</div>
          <div class="stat-sub">超阈值未上报</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">判定阈值</div>
          <div class="stat-value sm">{{ summary.threshold }}s</div>
          <div class="stat-sub">未上报超过该值即离线</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选条 -->
    <el-card shadow="never" class="bar-card">
      <div class="bar">
        <span class="bar-label">项目</span>
        <el-select v-model="projectId" placeholder="全部项目" clearable style="width: 200px">
          <el-option
            v-for="[id, name] in projectMap"
            :key="id"
            :label="name"
            :value="id"
          />
        </el-select>
        <span class="bar-label">设备类型</span>
        <el-select v-model="deviceType" placeholder="全部类型" clearable style="width: 160px">
          <el-option
            v-for="(label, type) in DEVICE_TYPE_LABELS"
            :key="type"
            :label="label"
            :value="type"
          />
        </el-select>
        <el-button type="primary" :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <span class="auto-tip">每 {{ POLL_MS / 1000 }}s 自动刷新 · 最近更新 {{ updatedAt }}</span>
      </div>
    </el-card>

    <!-- 主体：地图 + 明细 -->
    <el-row :gutter="12">
      <el-col :span="14">
        <el-card shadow="never" class="map-card">
          <template #header>
            <span class="card-title">实时设备分布</span>
            <span class="legend-inline">
              <i class="dot ok" />在线
              <i class="dot dim" />离线
            </span>
          </template>
          <MapPanel :devices="mapDevices" :fences="[]" height="480px" />
        </el-card>
      </el-col>

      <el-col :span="10">
        <!-- 按类型细分 -->
        <el-card shadow="never" class="type-card">
          <template #header><span class="card-title">按类型在线情况</span></template>
          <div v-if="byTypeList.length" class="type-row">
            <div v-for="t in byTypeList" :key="t.type" class="type-item">
              <div class="type-name">{{ t.label }}</div>
              <div class="type-bar">
                <span class="bar-ok" :style="{ width: (t.total ? (t.online / t.total) * 100 : 0) + '%' }" />
              </div>
              <div class="type-num">
                <span class="ok">{{ t.online }}</span> / <span class="dim">{{ t.offline }}</span> = {{ t.total }}
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无数据" :image-size="48" />
        </el-card>

        <!-- 设备明细表 -->
        <el-card shadow="never" class="table-card">
          <template #header><span class="card-title">设备明细</span></template>
          <el-table
            v-loading="loading"
            :data="items"
            border
            stripe
            height="360"
            class="table"
          >
            <el-table-column prop="device_no" label="设备编号" width="120" />
            <el-table-column label="名称" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ row.device_name || row.device_no }}</template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">{{ typeLabel(row.device_type) }}</template>
            </el-table-column>
            <el-table-column label="归属项目" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ projectName(row.project_id) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.online ? 'success' : 'info'" size="small">
                  {{ row.online ? '在线' : '离线' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最后上报" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ fmtTime(row.report_time) }}</template>
            </el-table-column>
            <el-table-column label="距今" width="90">
              <template #default="{ row }">{{ fmtAge(row.age_seconds) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.online {
  padding: 8px;
}
.cards {
  margin-bottom: 12px;
}
.stat {
  border-radius: 8px;
}
.stat-label {
  font-size: 13px;
  color: #909399;
}
.stat-value {
  font-size: 30px;
  font-weight: 700;
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
}
.stat-value.sm {
  font-size: 26px;
}
.stat-value.ok {
  color: #52c41a;
}
.stat-value.dim {
  color: #909399;
}
.stat-sub {
  font-size: 12px;
  color: #b4bccc;
  margin-top: 4px;
}
.online-card {
  border-top: 3px solid #52c41a;
}
.offline-card {
  border-top: 3px solid #909399;
}
.bar-card {
  margin-bottom: 12px;
}
.bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.bar-label {
  font-size: 13px;
  color: #606266;
}
.auto-tip {
  font-size: 12px;
  color: #b4bccc;
  margin-left: auto;
}
.map-card {
  margin-bottom: 12px;
}
.card-title {
  font-weight: 600;
}
.legend-inline {
  float: right;
  font-size: 12px;
  color: #606266;
}
.legend-inline .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin: 0 3px 0 10px;
  vertical-align: middle;
}
.dot.ok {
  background: #52c41a;
}
.dot.dim {
  background: #909399;
}
.type-card {
  margin-bottom: 12px;
}
.type-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.type-item {
  font-size: 13px;
}
.type-name {
  color: #303133;
  margin-bottom: 4px;
}
.type-bar {
  height: 8px;
  background: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
}
.bar-ok {
  display: block;
  height: 100%;
  background: #52c41a;
}
.type-num {
  font-size: 12px;
  color: #909399;
  margin-top: 3px;
}
.type-num .ok {
  color: #52c41a;
  font-weight: 600;
}
.type-num .dim {
  color: #909399;
}
.table-card {
  margin-bottom: 12px;
}
.table {
  width: 100%;
}
</style>
