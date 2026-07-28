<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from "vue";
import type { TableInstance } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  getCorrelations,
  getCorrelationMembers,
  getCorrelationTrend,
  getCorrelationHeatmap,
  runCorrelations,
  type CorrelationItem,
  type CorrelationMember,
  type CorrelationTrendPoint,
  type CorrelationHeatPoint,
} from "@/api/metrics";
import { createCorrelationSocket } from "@/utils/correlationWs";
import TrendLine from "@/components/TrendLine.vue";
import CorrelationHeatmap from "@/components/CorrelationHeatmap.vue";
import DispatchCreateDialog from "@/components/DispatchCreateDialog.vue";
import type { DispatchPreset } from "@/api/dispatch";

const auth = useAuthStore();

const canCreate = computed(() => auth.hasPermission("dispatch:create"));

const dispatchVisible = ref(false);
const dispatchPreset = ref<DispatchPreset | null>(null);
function openDispatch(row: CorrelationItem) {
  dispatchPreset.value = {
    source_type: "correlation",
    source_id: row.id,
    project_id: row.project_id,
    title:
      (row.root_cause_hint ? row.root_cause_hint.slice(0, 40) : "") ||
      `共因派单：事件组 #${row.id}`,
    root_cause_hint: row.root_cause_hint,
    level: row.max_level,
  };
  dispatchVisible.value = true;
}

const loading = ref(false);
const onlyCross = ref(false);
const items = ref<CorrelationItem[]>([]);
const trend = ref<CorrelationTrendPoint[]>([]);
const heatPoints = ref<CorrelationHeatPoint[]>([]);

// 热力图→列表 下钻联动：选中热点后筛选关联列表到该事件组（及同空间范围事件组）
const tableRef = ref<TableInstance>();
const selectedPoint = ref<CorrelationHeatPoint | null>(null);

// 命中判定：精确 id 匹配；同项目 + 同空间范围（网格/围栏）视为「同一地点下钻」
function matchScope(it: CorrelationItem, p: CorrelationHeatPoint): boolean {
  if (it.id === p.id) return true;
  if (it.project_id !== p.project_id) return false;
  if (it.spatial_type !== p.spatial_type) return false;
  if (p.spatial_type === "geo") return it.grid_cell === p.grid_cell;
  if (p.spatial_type === "fence") return it.fence_name === p.fence_name;
  return false;
}

const filteredItems = computed(() =>
  selectedPoint.value
    ? items.value.filter((it) => matchScope(it, selectedPoint.value!))
    : items.value,
);

function rowClass({ row }: { row: CorrelationItem }): string {
  return selectedPoint.value && row.id === selectedPoint.value.id
    ? "heat-active-row"
    : "";
}

function scopeTextOfPoint(p: CorrelationHeatPoint): string {
  if (p.spatial_type === "fence") return p.fence_name || "围栏";
  if (p.spatial_type === "geo") return `地理网格 ${p.grid_cell ?? ""}`.trim();
  return "单机";
}

// 成员明细懒加载缓存：groupId -> {loading, items}
const memberMap = reactive<Record<number, { loading: boolean; items: CorrelationMember[] }>>({});

const summary = computed(() => {
  const totalAlarms = items.value.reduce((s, it) => s + it.alarm_count, 0);
  const projects = new Set(items.value.map((it) => it.project_id).filter(Boolean));
  return {
    groups: items.value.length,
    cross: items.value.filter((it) => it.is_cross_device).length,
    alarms: totalAlarms,
    projects: projects.size,
  };
});

async function load() {
  loading.value = true;
  selectedPoint.value = null; // 重新加载后失效旧的筛选
  try {
    const [res, t, hm] = await Promise.all([
      getCorrelations(onlyCross.value, 100),
      getCorrelationTrend(30, onlyCross.value).catch(() => ({ series: [] as CorrelationTrendPoint[] })),
      getCorrelationHeatmap(onlyCross.value, 500).catch(() => ({
        points: [] as CorrelationHeatPoint[],
      })),
    ]);
    items.value = res.items;
    trend.value = t.series;
    heatPoints.value = hm.points;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载关联事件组失败");
  } finally {
    loading.value = false;
  }
}

const trendPoints = computed(() => trend.value.map((p) => ({ t: p.date, v: p.count })));

// 点击热力点：下钻联动到关联列表（筛选 + 高亮 + 自动展开命中事件组的成员明细）
async function onHeatSelect(p: CorrelationHeatPoint) {
  // 再次点击同一热点 → 取消筛选（切换）
  if (selectedPoint.value?.id === p.id) {
    selectedPoint.value = null;
    return;
  }
  selectedPoint.value = p;
  const exact = items.value.find((it) => it.id === p.id);
  if (exact) {
    await nextTick();
    tableRef.value?.toggleRowExpansion(exact, true);
    ElMessage.success(
      `已下钻：${p.project_name || "项目"} · ${scopeTextOfPoint(p)}（${p.alarm_count} 条告警）`,
    );
  } else {
    ElMessage.info(`已筛选该空间范围内 ${filteredItems.value.length} 个事件组`);
  }
}

// 清除热力图筛选
function clearHeatFilter() {
  selectedPoint.value = null;
}

async function onRecalc() {
  loading.value = true;
  try {
    const res = await runCorrelations();
    ElMessage.success(
      `关联计算完成：事件组 ${res.groups} 个，其中跨设备 ${res.cross_device_groups} 个`,
    );
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "关联计算失败");
  } finally {
    loading.value = false;
  }
}

async function onExpand(row: CorrelationItem, expandedRows: CorrelationItem[]) {
  const isOpen = expandedRows.includes(row);
  if (!isOpen) return;
  if (memberMap[row.id]) return; // 已加载
  memberMap[row.id] = { loading: true, items: [] };
  try {
    const res = await getCorrelationMembers(row.id);
    memberMap[row.id].items = res.items;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载成员告警失败");
  } finally {
    memberMap[row.id].loading = false;
  }
}

// YYYY-MM-DDTHH:mm:ss → MM-DD HH:mm（北京墙钟直读）
function fmtTime(ts: string | null): string {
  if (!ts) return "—";
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (m) return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
  return ts;
}

function scopeText(it: CorrelationItem): string {
  if (it.spatial_type === "fence") return it.fence_name || "围栏";
  if (it.spatial_type === "geo") return `地理网格 ${it.grid_cell}`;
  return `单机 ${it.device_nos?.[0] || "?"}`;
}

function scopeTag(it: CorrelationItem): "" | "success" | "warning" | "info" {
  if (it.spatial_type === "fence") return "success";
  if (it.spatial_type === "geo") return "warning";
  return "info";
}

function scopeLabel(it: CorrelationItem): string {
  if (it.spatial_type === "fence") return "围栏";
  if (it.spatial_type === "geo") return "地理";
  return "单机";
}

function levelTag(level: string | null): "" | "danger" | "warning" | "info" {
  switch (level) {
    case "严重":
      return "danger";
    case "警告":
      return "warning";
    case "提示":
      return "info";
    default:
      return "";
  }
}

// 实时推送：新增跨设备共因时弹通知并刷新列表/趋势（合并短时多次推送，避免刷新风暴）
let stopWs: (() => void) | null = null;
let refreshTimer: number | undefined;
function scheduleRefresh() {
  if (refreshTimer) return;
  refreshTimer = window.setTimeout(() => {
    refreshTimer = undefined;
    load();
  }, 1200);
}

function levelToNotify(level: string | null | undefined): "error" | "warning" | "info" {
  if (level === "严重") return "error";
  if (level === "警告") return "warning";
  return "info";
}

onMounted(() => {
  load();
  stopWs = createCorrelationSocket({
    onNew: (item) => {
      ElNotification({
        title: "新增跨设备共因",
        message: item.root_cause_hint || "发现新的跨设备共因事件组",
        type: levelToNotify(item.max_level),
        duration: 6000,
      });
      scheduleRefresh();
    },
  });
});

onUnmounted(() => {
  stopWs?.();
  stopWs = null;
  if (refreshTimer) window.clearTimeout(refreshTimer);
});
</script>

<template>
  <div class="corr-page">
    <el-card shadow="never" class="head-card">
      <div class="head">
        <div>
          <div class="title">跨设备根因关联</div>
          <div class="subtitle">
            将同项目、同空间范围（围栏 / 地理网格 / 单机）、时间近邻的告警聚合成事件组，
            揭示多台设备在同一区域短时集中告警的共因。数据每日随快照任务自动计算。
          </div>
        </div>
        <div class="actions">
          <el-switch
            v-model="onlyCross"
            active-text="仅看跨设备"
            @change="load"
          />
          <el-button
            v-if="auth.user?.is_superuser"
            type="primary"
            :loading="loading"
            @click="onRecalc"
          >
            重新计算
          </el-button>
        </div>
      </div>
      <div class="stats">
        <div class="stat">
          <div class="stat-num">{{ summary.groups }}</div>
          <div class="stat-label">事件组</div>
        </div>
        <div class="stat cross">
          <div class="stat-num">{{ summary.cross }}</div>
          <div class="stat-label">跨设备关联</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ summary.alarms }}</div>
          <div class="stat-label">涉及告警</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ summary.projects }}</div>
          <div class="stat-label">涉及项目</div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="trend-card">
      <div class="trend-head">
        <span class="card-title">关联事件组趋势（近 30 天）</span>
        <span class="trend-hint">{{ onlyCross ? "仅跨设备共因" : "全部事件组" }}</span>
      </div>
      <TrendLine
        v-if="trendPoints.length"
        :points="trendPoints"
        :height="56"
        :width="820"
        color="#e6a23c"
        :value-digits="0"
      />
      <el-empty v-else description="暂无趋势数据" :image-size="42" />
    </el-card>

    <el-card shadow="never" class="heat-card">
      <div class="trend-head">
        <span class="card-title">跨设备共因空间热力</span>
        <span class="trend-hint">
          按事件组代表坐标投影 · 热度=告警数 · {{ onlyCross ? "仅跨设备共因" : "全部事件组" }}
        </span>
      </div>
      <div v-if="selectedPoint" class="heat-filter">
        <el-tag type="primary" effect="light" size="small">
          已下钻：{{ selectedPoint.project_name || "项目" }} · {{ scopeTextOfPoint(selectedPoint) }}
          · 命中 {{ filteredItems.length }} 组
        </el-tag>
        <el-button link type="primary" size="small" @click="clearHeatFilter">
          清除筛选
        </el-button>
      </div>
      <CorrelationHeatmap
        :points="heatPoints"
        :height="360"
        :active-id="selectedPoint?.id ?? null"
        @select="onHeatSelect"
      />
    </el-card>

    <el-card shadow="never">
      <el-table
        ref="tableRef"
        :data="filteredItems"
        row-key="id"
        :row-class-name="rowClass"
        v-loading="loading"
        border
        stripe
        style="width: 100%"
        @expand-change="onExpand"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="members">
              <div v-if="!memberMap[row.id]" class="m-empty">展开以加载成员告警…</div>
              <div v-else-if="memberMap[row.id].loading" v-loading="true" class="m-loading" />
              <template v-else>
                <el-table :data="memberMap[row.id].items" size="small" border>
                  <el-table-column prop="device_no" label="设备编号" width="150" />
                  <el-table-column prop="alarm_type" label="类型" width="140" />
                  <el-table-column prop="alarm_level" label="级别" width="90">
                    <template #default="{ row: m }">
                      <el-tag :type="levelTag(m.alarm_level)" size="small" effect="light">
                        {{ m.alarm_level || "—" }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="alarm_status" label="状态" width="100" />
                  <el-table-column prop="handle_status" label="处置" width="100" />
                  <el-table-column prop="alarm_time" label="时间" width="130">
                    <template #default="{ row: m }">{{ fmtTime(m.alarm_time) }}</template>
                  </el-table-column>
                  <el-table-column prop="alarm_info" label="信息" min-width="200" />
                </el-table>
                <div
                  v-if="memberMap[row.id].items.length === 0"
                  class="m-empty"
                >
                  无可见成员告警（可能被数据范围过滤）
                </div>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="project_name" label="项目" min-width="160" />
        <el-table-column label="空间范围" min-width="180">
          <template #default="{ row }">
            <el-tag :type="scopeTag(row)" size="small" effect="light">
              {{ scopeLabel(row) }}
            </el-tag>
            <span class="scope-text">{{ scopeText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间窗" width="170">
          <template #default="{ row }">
            {{ fmtTime(row.started_at) }} ~ {{ fmtTime(row.ended_at) }}
          </template>
        </el-table-column>
        <el-table-column label="设备数" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_cross_device" type="danger" size="small" effect="dark">
              {{ row.device_count }} 跨设备
            </el-tag>
            <span v-else>{{ row.device_count }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="alarm_count" label="告警数" width="90" align="center" />
        <el-table-column label="最高级别" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="levelTag(row.max_level)" size="small" effect="light">
              {{ row.max_level || "—" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="root_cause_hint" label="根因提示" min-width="320" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canCreate"
              type="primary"
              link
              @click="openDispatch(row)"
            >
              派单
            </el-button>
          </template>
        </el-table-column>
        <template #empty>暂无关联事件组（近期无集中告警）</template>
      </el-table>
    </el-card>

    <DispatchCreateDialog v-model="dispatchVisible" :preset="dispatchPreset" />
  </div>
</template>

<style scoped>
.corr-page {
  padding: 4px;
}
.head-card {
  margin-bottom: 12px;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.title {
  font-size: 18px;
  font-weight: 600;
}
.subtitle {
  font-size: 13px;
  color: #909399;
  margin-top: 6px;
  line-height: 1.6;
  max-width: 880px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.stats {
  display: flex;
  gap: 14px;
  margin-top: 16px;
}
.stat {
  flex: 1;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 12px 16px;
  text-align: center;
}
.stat.cross {
  background: #fef0f0;
}
.stat-num {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}
.stat.cross .stat-num {
  color: #f56c6c;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.scope-text {
  margin-left: 8px;
  font-size: 13px;
  color: #606266;
}
.members {
  padding: 8px 12px;
  background: #fafafa;
}
.m-empty {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}
.m-loading {
  height: 80px;
}
.trend-card {
  margin-bottom: 12px;
}
.heat-card {
  margin-bottom: 12px;
}
.heat-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.heat-active-row {
  background: #ecf3ff !important;
}
.heat-active-row:hover > td {
  background: #e0ecff !important;
}
.trend-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 10px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.trend-hint {
  font-size: 12px;
  color: #909399;
}
</style>
