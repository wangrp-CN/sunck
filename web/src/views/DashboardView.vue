<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { Location } from "@element-plus/icons-vue";
import { getDashboardStats, getRecentAlarms } from "@/api/dashboard";
import {
  getRiskAlerts,
  getRiskTrend,
  getCorrelationSummary,
  getCorrelationTrend,
  RISK_ALERT_THRESHOLD,
  type RiskAlertItem,
  type CorrelationSummaryResp,
  type CorrelationTrendPoint,
} from "@/api/metrics";
import {
  fetchDevices,
  fetchLocations,
  type DeviceItem,
  type LocationItem,
} from "@/api/realtime";
import TrendLine from "@/components/TrendLine.vue";
import { fetchFences } from "@/api/fence";
import {
  exportAlarmReport,
  fetchSnapshotPreview,
  type Granularity,
  type SnapshotPreviewResult,
} from "@/api/alarm";
import { formatPeriodLabel, granularityLabel } from "@/utils/period";
import { wgs84ToGcj02 } from "@/utils/geo";
import { pct, tc, previewToTSV, snapTrendMaxOf } from "@/utils/snapshot";
import MapPanel from "@/components/MapPanel.vue";
import WorkPlanPopup from "@/components/WorkPlanPopup.vue";
import type { DashboardStats, MapDevice, MapFence, RecentAlarm } from "@/types";

const stats = ref<DashboardStats | null>(null);
const recent = ref<RecentAlarm[]>([]);
const loading = ref(false);
// 智能核心 v2：项目风险预警（阈值越阈，受数据范围约束）
const riskAlerts = ref<RiskAlertItem[]>([]);
const alertTrendMap = ref<Record<number, { t: string; v: number }[]>>({});
// 智能核心 v2：跨设备根因关联（今日新增共因卡片 + 近30天趋势）
const corrSummary = ref<CorrelationSummaryResp | null>(null);
const corrTrend = ref<CorrelationTrendPoint[]>([]);
const corrTrendPoints = computed(() =>
  corrTrend.value.map((p) => ({ t: p.date, v: p.count })),
);
// 趋势图按周期联动：粒度 + 时间范围（与告警报表/导出同一分桶口径）
const trendGranularity = ref<Granularity>("day");
const trendRange = ref<[string, string] | null>(null);
const snapshotExporting = ref<"" | "excel" | "pdf">("");

function fmtDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function mondayOf(d: Date): Date {
  const dow = (d.getDay() + 6) % 7; // 0=周一
  const r = new Date(d);
  r.setDate(d.getDate() - dow);
  return r;
}
function defaultRangeFor(g: Granularity): [string, string] {
  const today = new Date();
  if (g === "month") {
    const start = new Date(today.getFullYear(), today.getMonth() - 11, 1);
    const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    return [fmtDate(start), fmtDate(end)];
  }
  if (g === "week") {
    const mon = mondayOf(today);
    const start = new Date(mon);
    start.setDate(mon.getDate() - 12 * 7);
    const end = new Date(mon);
    end.setDate(mon.getDate() + 6);
    return [fmtDate(start), fmtDate(end)];
  }
  const start = new Date(today);
  start.setDate(today.getDate() - 6);
  return [fmtDate(start), fmtDate(today)];
}

const mapDevices = ref<MapDevice[]>([]);
const mapFences = ref<MapFence[]>([]);
const mapRef = ref<InstanceType<typeof MapPanel> | null>(null);
const selectedAlarmId = ref<number | null>(null);
// 围栏点击 → 关联作业计划弹层
const planPopup = reactive<{ visible: boolean; fenceId: number | null; fenceName: string }>({
  visible: false,
  fenceId: null,
  fenceName: "",
});
function onFenceClick(f: { id: number; name: string }) {
  planPopup.fenceId = f.id;
  planPopup.fenceName = f.name;
  planPopup.visible = true;
}
let timer: number | undefined;

// 点击告警项：在地图上聚焦/高亮对应设备
function focusAlarm(a: RecentAlarm) {
  selectedAlarmId.value = a.id;
  if (!a.device_no) return;
  const known = mapDevices.value.some((d) => d.device_no === a.device_no);
  if (known) {
    mapRef.value?.focusDevice(a.device_no);
  }
}

const DEVICE_LABELS: Record<string, string> = {
  locate: "人机定位",
  anti_intrusion: "大机防侵限",
  train_approach: "列车接近",
};
const LEVEL_COLORS: Record<string, string> = {
  严重: "#f56c6c",
  警告: "#e6a23c",
  提示: "#409eff",
};

function maxOf(arr: { count: number }[]): number {
  return Math.max(1, ...arr.map((x) => x.count));
}

const maxLevel = computed(() => maxOf(stats.value?.alarm_by_level ?? []));
const maxHandle = computed(() => maxOf(stats.value?.alarm_by_handle ?? []));
const maxDevice = computed(() => maxOf(stats.value?.device_by_type ?? []));
const trendPeriod = computed(() => stats.value?.alarm_trend_period ?? []);
const trendMax = computed(() => maxOf(trendPeriod.value));

const counts = computed(() => stats.value?.counts);

// 计数卡周期联动：告警总数→区间告警(窗口合计)，今日告警→本周期告警
const windowAlarms = computed(
  () => counts.value?.alarms_window ?? counts.value?.alarms ?? 0,
);
const currentPeriodAlarms = computed(
  () => counts.value?.alarms_current_period ?? counts.value?.alarms_today ?? 0,
);
// 「本周期」卡标题随粒度切换：今日 / 本周 / 本月
const currentPeriodCardLabel = computed(() => {
  const g = trendGranularity.value;
  return g === "month" ? "本月告警" : g === "week" ? "本周告警" : "今日告警";
});
// 窗口小字：起止范围
const windowRangeHint = computed(() => {
  const s = stats.value?.trend_start;
  const e = stats.value?.trend_end;
  return s && e ? `${s} ~ ${e}` : "";
});
// 当前周期小字：格式化 current_period
const currentPeriodHint = computed(() => {
  const p = stats.value?.current_period;
  return p ? formatPeriodLabel(p, trendGranularity.value) : "";
});

// 设备在线率 / 围栏统计（周期联动卡）
const deviceStats = computed(() => stats.value?.device_stats);
const fenceStats = computed(() => stats.value?.fence_stats);
const onlineRateText = computed(() => {
  const r = deviceStats.value?.online_rate;
  return r == null ? "—" : `${r}%`;
});

function levelColor(level: string | null): string {
  return (level && LEVEL_COLORS[level]) || "#909399";
}

// 风险预警分档配色（高红/中橙/低绿）
function alertRiskTag(level?: string | null): "" | "success" | "warning" | "danger" {
  switch (level) {
    case "高":
      return "danger";
    case "中":
      return "warning";
    default:
      return "success";
  }
}
function alertRiskColor(level?: string | null): string {
  switch (level) {
    case "高":
      return "#f56c6c";
    case "中":
      return "#e6a23c";
    default:
      return "#67c23a";
  }
}

function fmtTime(t: string | null): string {
  if (!t) return "—";
  return t.replace("T", " ").slice(0, 19);
}

// 越阈项目近 30 天风险趋势（仅对越阈项目拉取，数量很少）
async function loadAlertTrends() {
  const items = riskAlerts.value;
  if (!items.length) {
    alertTrendMap.value = {};
    return;
  }
  try {
    const results = await Promise.all(
      items.map((it) => getRiskTrend(it.project_id, 30).catch(() => ({ series: [] as any[] }))),
    );
    const map: Record<number, { t: string; v: number }[]> = {};
    items.forEach((it, i) => {
      map[it.project_id] = (results[i].series || []).map((s) => ({
        t: s.snapshot_at,
        v: s.risk_index,
      }));
    });
    alertTrendMap.value = map;
  } catch {
    /* 静默 */
  }
}

async function load() {
  loading.value = true;
  try {
    const [st, r] = await Promise.all([
      getDashboardStats({
        granularity: trendGranularity.value,
        start: trendRange.value
          ? `${trendRange.value[0]}T00:00:00`
          : undefined,
        end: trendRange.value
          ? `${trendRange.value[1]}T23:59:59.999999`
          : undefined,
      }),
      getRecentAlarms(20),
    ]);
    stats.value = st;
    recent.value = r.items;
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false;
  }
  // 风险预警独立加载：即便 metrics 接口异常也不影响主面板
  void loadAlerts();
  // 跨设备关联汇总/趋势独立加载（同上，互不影响主面板）
  void loadCorrelation();
}

async function loadCorrelation() {
  try {
    const [s, t] = await Promise.all([
      getCorrelationSummary(),
      getCorrelationTrend(30, true).catch(() => ({ series: [] as CorrelationTrendPoint[] })),
    ]);
    corrSummary.value = s;
    corrTrend.value = t.series;
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadAlerts() {
  try {
    const alerts = await getRiskAlerts();
    riskAlerts.value = alerts.items || [];
    await loadAlertTrends();
  } catch {
    /* 拦截器已提示 */
  }
}

function onGranularityChange() {
  trendRange.value = defaultRangeFor(trendGranularity.value);
  load();
}
function onRangeChange() {
  load();
}
function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
async function doExportSnapshot(fmt: "excel" | "pdf") {
  if (!trendRange.value) {
    ElMessage.warning("请选择历史快照的起始与结束日期");
    return;
  }
  snapshotExporting.value = fmt;
  try {
    const blob = await exportAlarmReport(fmt, {
      granularity: trendGranularity.value,
      start: `${trendRange.value[0]}T00:00:00`,
      end: `${trendRange.value[1]}T23:59:59.999999`,
      snapshot: true,
    });
    const ext = fmt === "excel" ? "xlsx" : "pdf";
    const tag = `${trendGranularity.value}_${trendRange.value[0]}_${trendRange.value[1]}`;
    triggerDownload(blob, `告警快照_${tag}.${ext}`);
    ElMessage.success(
      `已导出${granularityLabel(trendGranularity.value)}历史快照 (${ext.toUpperCase()})`,
    );
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "快照导出失败";
    ElMessage.error(message);
  } finally {
    snapshotExporting.value = "";
  }
}

// ----- 仪表盘趋势卡：历史快照预览入口 -----
const snapPreviewVisible = ref(false);
const snapPreview = ref<SnapshotPreviewResult | null>(null);
const snapPreviewLoading = ref(false);
const snapPreviewExporting = ref<"" | "excel" | "pdf">("");

// 占比小数 → 百分比文本（见 @/utils/snapshot 的 pct）
// 按项目汇总表合计行（告警数 / 待处理 / 已处置 求和）
function projectSummaryMethod({ columns, data }: any): string[] {
  const sums: string[] = [];
  columns.forEach((col: any, index: number) => {
    if (index === 0) {
      sums[index] = "合计";
      return;
    }
    if (col.property === "count") {
      sums[index] = data.reduce((s: number, d: any) => s + (d.count || 0), 0).toString();
    } else if (col.property === "pending") {
      sums[index] = data.reduce((s: number, d: any) => s + (d.pending || 0), 0).toString();
    } else if (col.property === "handled") {
      sums[index] = data.reduce((s: number, d: any) => s + (d.handled || 0), 0).toString();
    } else {
      sums[index] = "";
    }
  });
  return sums;
}

// 打开快照预览弹层（与导出同源 JSON），确认后再导出
async function openSnapshotPreview() {
  if (!trendRange.value) {
    ElMessage.warning("请选择历史快照的起始与结束日期");
    return;
  }
  snapPreviewVisible.value = true;
  snapPreviewLoading.value = true;
  try {
    const data = await fetchSnapshotPreview({
      granularity: trendGranularity.value,
      start: `${trendRange.value[0]}T00:00:00`,
      end: `${trendRange.value[1]}T23:59:59.999999`,
    });
    snapPreview.value = data;
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "快照预览失败";
    ElMessage.error(message);
  } finally {
    snapPreviewLoading.value = false;
  }
}

// 预览弹层内直接导出（复用当前趋势卡的粒度与范围）
async function exportFromPreview(fmt: "excel" | "pdf") {
  if (!trendRange.value) {
    ElMessage.warning("请选择历史快照的起始与结束日期");
    return;
  }
  snapPreviewExporting.value = fmt;
  try {
    const blob = await exportAlarmReport(fmt, {
      granularity: trendGranularity.value,
      start: `${trendRange.value[0]}T00:00:00`,
      end: `${trendRange.value[1]}T23:59:59.999999`,
      snapshot: true,
    });
    const ext = fmt === "excel" ? "xlsx" : "pdf";
    const tag = `${trendGranularity.value}_${trendRange.value[0]}_${trendRange.value[1]}`;
    triggerDownload(blob, `告警快照_${tag}.${ext}`);
    ElMessage.success(
      `已导出${granularityLabel(trendGranularity.value)}历史快照 (${ext.toUpperCase()})`,
    );
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "快照导出失败";
    ElMessage.error(message);
  } finally {
    snapPreviewExporting.value = "";
  }
}

// 迷你趋势图：预览弹层内按周期柱状图的最大刻度
const snapTrendMax = computed(() => snapTrendMaxOf(snapPreview.value?.periods ?? []));

// 剪切板写入（优先 clipboard API，非安全上下文降级到 execCommand）
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 降级 */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

// 把预览结果拼成 TSV（逻辑见 @/utils/snapshot 的 previewToTSV，纯函数可单测）
async function copyPreviewAsTable() {
  if (!snapPreview.value) {
    ElMessage.warning("暂无可复制的预览数据");
    return;
  }
  const text = previewToTSV(snapPreview.value);
  const ok = await copyText(text);
  if (ok) {
    ElMessage.success("已复制为表格文本（可直接粘贴到 Excel）");
  } else {
    ElMessage.error("复制失败，请手动选择文本复制");
  }
}

// 地图数据：实时位置（GCJ-02）+ 配置坐标（WGS-84 转 GCJ-02）+ 围栏
async function loadMap() {
  try {
    const [locRes, devRes, fenceRes] = await Promise.all([
      fetchLocations(),
      fetchDevices(),
      fetchFences({ page: 1, size: 200 }),
    ]);
    const liveMap = new Map<string, LocationItem>();
    for (const l of locRes.items) {
      if (l.gcj02) liveMap.set(l.device_no, l);
    }
    const devs: MapDevice[] = [];
    for (const d of devRes.items as DeviceItem[]) {
      const live = liveMap.get(d.device_no);
      if (live && live.gcj02) {
        devs.push({
          device_no: d.device_no,
          name: live.device_name || d.name,
          device_type: live.device_type,
          lng: live.gcj02.lng,
          lat: live.gcj02.lat,
          status: live.status,
          live: true,
        });
      } else if (d.longitude != null && d.latitude != null) {
        const [lng, lat] = wgs84ToGcj02(d.longitude, d.latitude);
        devs.push({
          device_no: d.device_no,
          name: d.name,
          device_type: d.device_type,
          lng,
          lat,
          status: d.status,
          live: false,
        });
      }
    }
    mapDevices.value = devs;
    mapFences.value = (fenceRes.items || []).map((f) => ({
      id: f.id,
      name: f.name,
      geometry_wkt: f.geometry_wkt,
    }));
  } catch {
    // 拦截器已提示
  }
}

onMounted(() => {
  trendRange.value = defaultRangeFor(trendGranularity.value);
  load();
  loadMap();
  timer = window.setInterval(() => {
    load();
    loadMap();
  }, 15000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <!-- 统计卡片 -->
    <div class="stat-row">
      <div class="stat-card" v-if="counts">
        <div class="stat-num">{{ counts.projects }}</div>
        <div class="stat-label">工程项目</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ counts?.devices ?? 0 }}</div>
        <div class="stat-label">设备总数</div>
      </div>
      <div class="stat-card online" v-if="deviceStats">
        <div class="stat-num">{{ onlineRateText }}</div>
        <div class="stat-label">
          设备在线率
          <span class="stat-sub" v-if="windowRangeHint">{{ windowRangeHint }}</span>
          <span class="stat-sub">在线 {{ deviceStats.online }} / 总 {{ deviceStats.total }} · 区间活跃 {{ deviceStats.window_active }}</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ counts?.persons ?? 0 }}</div>
        <div class="stat-label">人员</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ counts?.machines ?? 0 }}</div>
        <div class="stat-label">大型机械</div>
      </div>
      <div class="stat-card" v-if="fenceStats">
        <div class="stat-num">{{ fenceStats.total }}</div>
        <div class="stat-label">
          电子围栏
          <span class="stat-sub" v-if="windowRangeHint">{{ windowRangeHint }}</span>
          <span class="stat-sub">窗口内监控 {{ fenceStats.monitored_in_window }} · 启用 {{ fenceStats.enabled }}</span>
        </div>
      </div>
      <div class="stat-card danger">
        <div class="stat-num">{{ windowAlarms }}</div>
        <div class="stat-label">
          区间告警
          <span class="stat-sub" v-if="windowRangeHint">{{ windowRangeHint }}</span>
        </div>
      </div>
      <div class="stat-card danger">
        <div class="stat-num">{{ currentPeriodAlarms }}</div>
        <div class="stat-label">
          {{ currentPeriodCardLabel }}
          <span class="stat-sub" v-if="currentPeriodHint">{{ currentPeriodHint }}</span>
        </div>
      </div>
    </div>

    <el-row :gutter="16" class="main-row">
      <!-- 左：地图占位 + 实时告警 -->
      <el-col :span="16">
        <el-card class="map-card" shadow="never">
          <template #header>
            <span class="card-title">工程地图 / 轨迹</span>
            <span class="map-legend">
              <i class="lg-dot lg-live"></i>实时
              <i class="lg-dot lg-cfg"></i>配置
            </span>
          </template>
          <MapPanel
            ref="mapRef"
            :devices="mapDevices"
            :fences="mapFences"
            height="320px"
            @fence-click="onFenceClick"
          />
        </el-card>

        <el-card class="alarm-card" shadow="never">
          <template #header>
            <span class="card-title">实时告警流</span>
            <span class="live-dot" /> 实时
          </template>
          <div class="alarm-list">
            <div
              v-for="a in recent"
              :key="a.id"
              class="alarm-item"
              :class="{ active: selectedAlarmId === a.id, clickable: !!a.device_no }"
              :style="{ borderLeftColor: levelColor(a.alarm_level) }"
              @click="focusAlarm(a)"
            >
              <div class="alarm-head">
                <el-tag :color="levelColor(a.alarm_level)" size="small" effect="dark">
                  {{ a.alarm_level || "—" }}
                </el-tag>
                <span class="alarm-name">{{ a.device_name || a.device_no || "—" }}</span>
                <span v-if="a.device_no" class="alarm-locate">
                  <el-icon><Location /></el-icon>定位
                </span>
                <span class="alarm-time">{{ fmtTime(a.alarm_time) }}</span>
              </div>
              <div class="alarm-info">{{ a.alarm_info || a.alarm_type || "—" }}</div>
            </div>
            <el-empty v-if="recent.length === 0" description="暂无告警" :image-size="60" />
          </div>
        </el-card>
      </el-col>

      <!-- 右：分布条形 -->
      <el-col :span="8">
        <!-- 智能核心 v2：项目风险预警（阈值越阈，含 is_new 上升沿标记） -->
        <el-card shadow="never" class="bar-card alert-card">
          <template #header>
            <div class="card-head">
              <span class="card-title">项目风险预警</span>
              <span class="card-sub">阈值 {{ RISK_ALERT_THRESHOLD }}</span>
            </div>
          </template>
          <template v-if="riskAlerts.length">
            <div v-for="a in riskAlerts" :key="a.project_id" class="alert-row">
              <div class="alert-row-head">
                <span class="alert-name">{{ a.project_name }}</span>
                <el-tag v-if="a.is_new" type="danger" size="small" effect="dark">新</el-tag>
                <el-tag :type="alertRiskTag(a.risk_level)" size="small">
                  {{ a.risk_level || "—" }}
                </el-tag>
                <span class="alert-idx" :style="{ color: alertRiskColor(a.risk_level) }">
                  {{ a.risk_index }}
                </span>
              </div>
              <TrendLine
                v-if="(alertTrendMap[a.project_id] || []).length"
                :points="alertTrendMap[a.project_id]"
                :threshold="RISK_ALERT_THRESHOLD"
                :color="alertRiskColor(a.risk_level)"
                :height="34"
                :width="248"
              />
              <span v-else class="muted">暂无趋势</span>
            </div>
          </template>
          <el-empty v-else description="暂无越阈项目" :image-size="40" />
        </el-card>

        <!-- 智能核心 v2：今日新增跨设备共因（关联事件组，受数据范围约束） -->
        <el-card shadow="never" class="bar-card corr-card">
          <template #header>
            <div class="card-head">
              <span class="card-title">今日新增跨设备共因</span>
              <span class="card-sub">近 30 天趋势</span>
            </div>
          </template>
          <div class="corr-bignum">{{ corrSummary?.today_cross_device ?? "—" }}</div>
          <div class="corr-sub">
            涉及项目 {{ corrSummary?.today_projects ?? "—" }} 个 · 累计跨设备
            {{ corrSummary?.cross_device_total ?? "—" }}
          </div>
          <TrendLine
            v-if="corrTrendPoints.length"
            :points="corrTrendPoints"
            :height="40"
            :width="248"
            color="#f56c6c"
            :value-digits="0"
          />
          <span v-else class="muted">暂无趋势</span>
        </el-card>

        <el-card shadow="never" class="bar-card">
          <template #header>
            <div class="card-head">
              <span class="card-title">告警级别分布</span>
              <span class="card-sub" v-if="windowRangeHint">{{ windowRangeHint }}</span>
            </div>
          </template>
          <div v-for="x in stats?.alarm_by_level" :key="x.level" class="bar-row">
            <span class="bar-label">{{ x.level }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: (x.count / maxLevel * 100) + '%', background: levelColor(x.level) }"
              />
            </div>
            <span class="bar-val">{{ x.count }}</span>
          </div>
        </el-card>

        <el-card shadow="never" class="bar-card">
          <template #header>
            <div class="card-head">
              <span class="card-title">告警处理状态</span>
              <span class="card-sub" v-if="windowRangeHint">{{ windowRangeHint }}</span>
            </div>
          </template>
          <div v-for="x in stats?.alarm_by_handle" :key="x.status" class="bar-row">
            <span class="bar-label">{{ x.status }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: (x.count / maxHandle * 100) + '%', background: '#409eff' }"
              />
            </div>
            <span class="bar-val">{{ x.count }}</span>
          </div>
        </el-card>

        <el-card shadow="never" class="bar-card">
          <template #header><span class="card-title">设备类型分布</span></template>
          <div v-for="x in stats?.device_by_type" :key="x.device_type" class="bar-row">
            <span class="bar-label">{{ DEVICE_LABELS[x.device_type] || x.device_type }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: (x.count / maxDevice * 100) + '%', background: '#67c23a' }"
              />
            </div>
            <span class="bar-val">{{ x.count }}</span>
          </div>
        </el-card>

        <el-card shadow="never" class="bar-card trend-card">
          <template #header>
            <div class="card-head">
              <span class="card-title">告警趋势（按周期联动）</span>
              <span class="trend-controls">
                <el-radio-group v-model="trendGranularity" size="small" @change="onGranularityChange">
                  <el-radio-button label="day">天</el-radio-button>
                  <el-radio-button label="week">周</el-radio-button>
                  <el-radio-button label="month">月</el-radio-button>
                </el-radio-group>
                <el-date-picker
                  v-model="trendRange"
                  type="daterange"
                  size="small"
                  value-format="YYYY-MM-DD"
                  range-separator="~"
                  start-placeholder="起始"
                  end-placeholder="结束"
                  :clearable="false"
                  @change="onRangeChange"
                  style="width: 220px"
                />
                <el-button
                  size="small"
                  type="primary"
                  :loading="snapshotExporting === 'excel'"
                  @click="doExportSnapshot('excel')"
                >导出快照 Excel</el-button>
                <el-button
                  size="small"
                  :loading="snapshotExporting === 'pdf'"
                  @click="doExportSnapshot('pdf')"
                >PDF</el-button>
                <el-button
                  size="small"
                  @click="openSnapshotPreview"
                >快照预览</el-button>
              </span>
            </div>
          </template>
          <div class="trend-range-hint">
            粒度：{{ granularityLabel(trendGranularity) }} · 窗口 {{ stats?.trend_start }} ~ {{ stats?.trend_end }} · 共 {{ trendPeriod.length }} 个周期
          </div>
          <div v-for="x in trendPeriod" :key="x.period" class="bar-row">
            <span class="bar-label">{{ formatPeriodLabel(x.period, trendGranularity) }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: (x.count / trendMax * 100) + '%', background: '#e6a23c' }"
              />
            </div>
            <span class="bar-val">{{ x.count }}</span>
          </div>
          <el-empty v-if="trendPeriod.length === 0" description="该时间范围内暂无告警" :image-size="50" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 围栏点击 → 关联作业计划详情 -->
    <WorkPlanPopup
      v-model="planPopup.visible"
      :fence-id="planPopup.fenceId"
      :fence-name="planPopup.fenceName"
    />

    <!-- 历史快照预览（与导出 Excel/PDF 同源） -->
    <el-dialog
      v-model="snapPreviewVisible"
      title="历史快照预览"
      width="760px"
      top="5vh"
      append-to-body
      destroy-on-close
    >
      <div v-loading="snapPreviewLoading" class="snapshot-preview">
        <template v-if="snapPreview">
          <div class="snapshot-preview-meta">
            <span>筛选：{{ snapPreview.meta.filters_desc }}</span>
            <span>生成：{{ snapPreview.meta.generated_at }}</span>
            <span>
              共 {{ snapPreview.period_keys.length }} 个{{
                granularityLabel(snapPreview.granularity as any)
              }}周期 · 告警 {{ snapPreview.summary.total }} 条
            </span>
          </div>

          <!-- 迷你趋势图：按周期柱状图 · 按类型分色堆叠（与 PDF/Excel 同源） -->
          <div class="preview-title">
            预览趋势（按周期 · 按类型堆叠）
            <span class="preview-title-sub">共 {{ snapPreview.periods.length }} 个周期</span>
          </div>
          <div class="mini-legend">
            <span><i style="background:#C00000" />围栏侵入</span>
            <span><i style="background:#ED7D31" />间距过近</span>
            <span><i style="background:#2E75B6" />设备自报</span>
          </div>
          <div class="mini-trend">
            <div
              v-for="x in snapPreview.periods"
              :key="x.period"
              class="bar-row"
            >
              <span class="bar-label">{{
                formatPeriodLabel(x.period, snapPreview.granularity as any)
              }}</span>
              <div class="bar-track stack">
                <div
                  class="bar-seg"
                  :style="{
                    width: (tc(x.by_type, 'fence_intrusion') / snapTrendMax * 100) + '%',
                    background: '#C00000',
                  }"
                  :title="'围栏侵入 ' + tc(x.by_type, 'fence_intrusion')"
                />
                <div
                  class="bar-seg"
                  :style="{
                    width: (tc(x.by_type, 'distance_too_close') / snapTrendMax * 100) + '%',
                    background: '#ED7D31',
                  }"
                  :title="'间距过近 ' + tc(x.by_type, 'distance_too_close')"
                />
                <div
                  class="bar-seg"
                  :style="{
                    width: (tc(x.by_type, 'device_alarm') / snapTrendMax * 100) + '%',
                    background: '#2E75B6',
                  }"
                  :title="'设备自报 ' + tc(x.by_type, 'device_alarm')"
                />
              </div>
              <span class="bar-val">{{ x.total }}</span>
            </div>
            <el-empty
              v-if="snapPreview.periods.length === 0"
              description="该时间范围内暂无告警"
              :image-size="40"
            />
          </div>

          <!-- 概览指标 -->
          <div class="stat-cards mini">
            <div class="stat-card">
              <div class="stat-num">{{ snapPreview.summary.total }}</div>
              <div class="stat-label">告警总数</div>
            </div>
            <div class="stat-card ok">
              <div class="stat-num">{{ snapPreview.summary.handled }}</div>
              <div class="stat-label">已处置</div>
            </div>
            <div class="stat-card warn">
              <div class="stat-num">{{ snapPreview.summary.pending }}</div>
              <div class="stat-label">待处理</div>
            </div>
            <div class="stat-card">
              <div class="stat-num">{{ (snapPreview.summary.handle_rate * 100).toFixed(1) }}%</div>
              <div class="stat-label">处置率</div>
            </div>
          </div>

          <!-- 各周期分布（可展开看按项目拆分） -->
          <div class="preview-title">各周期告警分布</div>
          <el-table :data="snapPreview.periods" border stripe size="small" max-height="300">
            <el-table-column type="expand">
              <template #default="{ row }">
                <el-table :data="row.by_project" border size="small" style="width: 100%">
                  <el-table-column prop="project_name" label="项目" min-width="160" />
                  <el-table-column prop="count" label="告警数" width="90" />
                  <el-table-column label="按级别" min-width="160">
                    <template #default="{ row: p }">
                      <span v-for="(v, k) in p.by_level" :key="k" class="sub-chip">
                        {{ k }}: {{ v }}
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="period" label="周期" width="140" />
            <el-table-column prop="total" label="总数" width="80" />
            <el-table-column label="围栏侵入" width="90">
              <template #default="{ row }">{{ row.by_type.fence_intrusion ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="间距过近" width="90">
              <template #default="{ row }">{{ row.by_type.distance_too_close ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="设备自报" width="90">
              <template #default="{ row }">{{ row.by_type.device_alarm ?? 0 }}</template>
            </el-table-column>
            <el-table-column prop="pending" label="待处理" width="80" />
            <el-table-column prop="handled" label="已处置" width="80" />
            <template #empty>该时间范围内暂无告警</template>
          </el-table>

          <!-- 按项目汇总 -->
          <div class="preview-title">按项目汇总（跨整个窗口）</div>
          <el-table
            :data="snapPreview.project_summary"
            border
            stripe
            size="small"
            max-height="300"
            show-summary
            :summary-method="projectSummaryMethod"
          >
            <el-table-column prop="project_name" label="项目" min-width="160" />
            <el-table-column prop="count" label="告警数" width="90" />
            <el-table-column label="占比" width="90">
              <template #default="{ row }">{{ pct(row.ratio) }}</template>
            </el-table-column>
            <el-table-column label="围栏侵入" width="90">
              <template #default="{ row }">{{ row.by_type.fence_intrusion ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="间距过近" width="90">
              <template #default="{ row }">{{ row.by_type.distance_too_close ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="设备自报" width="90">
              <template #default="{ row }">{{ row.by_type.device_alarm ?? 0 }}</template>
            </el-table-column>
            <el-table-column prop="pending" label="待处理" width="80" />
            <el-table-column prop="handled" label="已处置" width="80" />
            <template #empty>无项目数据</template>
          </el-table>
        </template>
      </div>
      <template #footer>
        <el-button @click="snapPreviewVisible = false">关闭</el-button>
        <el-button
          :disabled="!snapPreview"
          @click="copyPreviewAsTable"
        >复制为表格</el-button>
        <el-button
          type="success"
          :loading="snapPreviewExporting === 'excel'"
          :disabled="!snapPreview"
          @click="exportFromPreview('excel')"
        >导出快照 Excel</el-button>
        <el-button
          :loading="snapPreviewExporting === 'pdf'"
          :disabled="!snapPreview"
          @click="exportFromPreview('pdf')"
        >导出快照 PDF</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 8px;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  border-top: 3px solid #409eff;
}
.stat-card.online {
  border-top-color: #67c23a;
}
.stat-card.danger {
  border-top-color: #f56c6c;
}
.stat-num {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
.stat-sub {
  display: block;
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
  white-space: nowrap;
}
.main-row {
  align-items: stretch;
}
.card-title {
  font-weight: 600;
}
/* 非 trend-card 内的卡片头部（标题 + 右侧小字，如级别/处理状态分布卡） */
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.card-sub {
  font-size: 11px;
  color: #c0c4cc;
  white-space: nowrap;
}

.map-card {
  margin-bottom: 16px;
}
.map-legend {
  float: right;
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}
.lg-dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin: 0 4px 0 10px;
  vertical-align: middle;
  border: 2px solid #fff;
  box-shadow: 0 0 3px rgba(0, 0, 0, 0.3);
}
.lg-live {
  background: #52c41a;
}
.lg-cfg {
  background: #2f54eb;
}
.alarm-card {
  height: 460px;
}
.live-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #67c23a;
  margin-left: 8px;
  animation: blink 1.2s infinite;
}
@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}
.alarm-list {
  max-height: 380px;
  overflow-y: auto;
}
.alarm-item {
  border-left: 3px solid #ddd;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #fafafa;
  border-radius: 0 6px 6px 0;
  transition: background 0.15s, box-shadow 0.15s;
}
.alarm-item.clickable {
  cursor: pointer;
}
.alarm-item.clickable:hover {
  background: #f0f5ff;
}
.alarm-item.active {
  background: #e8f2ff;
  box-shadow: inset 0 0 0 1px #409eff;
}
.alarm-locate {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: #409eff;
}
.alarm-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.alarm-name {
  font-weight: 600;
  color: #303133;
}
.alarm-time {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}
.alarm-info {
  font-size: 13px;
  color: #606266;
  margin-top: 4px;
}
.bar-card {
  margin-bottom: 16px;
}
.trend-card .card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.trend-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.trend-range-hint {
  font-size: 12px;
  color: #909399;
  margin-bottom: 10px;
}
.bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.bar-label {
  width: 72px;
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}
.bar-track {
  flex: 1;
  height: 14px;
  background: #f0f2f5;
  border-radius: 7px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 7px;
  transition: width 0.4s ease;
}
.bar-val {
  width: 32px;
  text-align: right;
  font-size: 13px;
  color: #303133;
}
/* 预览迷你图：按类型分色堆叠（与 PDF/Excel 同源） */
.bar-track.stack {
  display: flex;
  border-radius: 7px;
}
.bar-seg {
  height: 100%;
  min-width: 0;
  transition: width 0.4s ease;
}
.bar-seg:first-child {
  border-radius: 7px 0 0 7px;
}
.bar-seg:last-child {
  border-radius: 0 7px 7px 0;
}
.mini-legend {
  display: flex;
  gap: 14px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #606266;
}
.mini-legend span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.mini-legend i {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}

/* 历史快照预览弹层（与导出 Excel/PDF 同源） */
.stat-cards.mini {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.stat-cards.mini .stat-card {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 8px;
  text-align: center;
}
.stat-cards.mini .stat-num {
  font-size: 20px;
  font-weight: 700;
  color: #303133;
}
.stat-cards.mini .stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.stat-cards.mini .stat-card.ok {
  background: #f0f9eb;
  border-color: #e1f3d8;
}
.stat-cards.mini .stat-card.warn {
  background: #fef0f0;
  border-color: #fde2e2;
}
.stat-cards.mini .stat-card.ok .stat-num {
  color: #67c23a;
}
.stat-cards.mini .stat-card.warn .stat-num {
  color: #f56c6c;
}
.preview-title {
  font-size: 13px;
  font-weight: 600;
  color: #4a5568;
  margin: 8px 0;
}
.snapshot-preview {
  max-height: 72vh;
  overflow-y: auto;
}
.snapshot-preview-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 12px;
}
.sub-chip {
  display: inline-block;
  font-size: 12px;
  color: #606266;
  background: #f0f2f5;
  border-radius: 4px;
  padding: 1px 6px;
  margin: 0 4px 4px 0;
}
/* 预览迷你趋势图：复用概览的 bar-row / bar-track / bar-fill 分桶样式 */
.mini-trend {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 6px;
}
.preview-title-sub {
  font-size: 12px;
  font-weight: 400;
  color: #c0c4cc;
  margin-left: 8px;
}
/* 项目风险预警卡 */
.alert-card {
  margin-bottom: 16px;
  border-top: 3px solid #f56c6c;
}
/* 今日新增跨设备共因卡 */
.corr-card {
  margin-bottom: 16px;
  border-top: 3px solid #f56c6c;
}
.corr-bignum {
  font-size: 30px;
  font-weight: 700;
  color: #f56c6c;
  line-height: 1.1;
}
.corr-sub {
  font-size: 12px;
  color: #909399;
  margin: 4px 0 8px;
}
.alert-row {
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
}
.alert-row:last-child {
  border-bottom: none;
}
.alert-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.alert-name {
  font-weight: 600;
  color: #303133;
  font-size: 13px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.alert-idx {
  font-weight: 700;
  font-size: 15px;
}
.muted {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
