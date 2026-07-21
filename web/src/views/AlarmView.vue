<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  DEVICE_TYPE_LABELS,
  fetchAlarms,
  fetchDevices,
  fetchLocations,
  type DeviceItem,
  type LocationItem,
} from "@/api/realtime";
import {
  exportAlarmReport,
  fetchAlarmPeriod,
  fetchAlarmReport,
  fetchAlarmTrend,
  fetchSnapshotPreview,
  getAlarmConfig,
  handleAlarm,
  updateAlarmConfig,
  type AlarmReportParams,
  type AlarmReportResult,
  type Granularity,
  type SnapshotPreviewResult,
} from "@/api/alarm";
import { formatPeriodLabel, granularityLabel } from "@/utils/period";
import { fetchProjects } from "@/api/project";
import { fetchFences } from "@/api/fence";
import { putAlarmMedia } from "@/api/media";
import { mediaKeyFromUrl, resolvePresigned } from "@/utils/media";
import { wgs84ToGcj02 } from "@/utils/geo";
import { tc, snapTrendMaxOf } from "@/utils/snapshot";
import MapPanel from "@/components/MapPanel.vue";
import DailyTrendChart from "@/components/DailyTrendChart.vue";
import WorkPlanPopup from "@/components/WorkPlanPopup.vue";
import MediaUpload from "@/components/MediaUpload.vue";
import type { Alarm, AlarmConfig, MapDevice, MapFence, Project } from "@/types";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const canHandle = computed(() => auth.user?.permission_codes.includes("alarm:handle") ?? false);
const canConfig = computed(() => auth.user?.permission_codes.includes("alarm:config") ?? false);
const canReport = computed(() => auth.user?.permission_codes.includes("alarm:list") ?? false);

// 地图与告警联动
const mapRef = ref<InstanceType<typeof MapPanel> | null>(null);
const mapDevices = ref<MapDevice[]>([]);
const mapFences = ref<MapFence[]>([]);
const liveByNo = reactive<Record<string, LocationItem>>({});
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

const ALARM_TYPE_LABELS: Record<string, string> = {
  fence_intrusion: "围栏侵入",
  distance_too_close: "间距过近",
  device_alarm: "设备告警",
};
const HANDLE_OPTIONS = ["待处理", "已处理", "已忽略", "已确认", "已消警"];
const STATUS_OPTIONS = ["告警开始", "告警结束", "已消警"];

const projects = ref<Project[]>([]);
const list = ref<Alarm[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);
// 告警媒体 URL（代理 URL）→ 部门隔离的预签名直连 URL 映射（关闭 #10 公开缺口）
const mediaSrc = ref<Record<string, string>>({});
const filters = reactive({
  project_id: null as number | null,
  alarm_type: "" as string,
  handle_status: "" as string,
  alarm_status: "" as string,
});
// 报表/导出共享的时间范围（[start, end]，ISO 字符串）
const timeRange = ref<[string, string] | null>(null);

// 组装报表/导出参数（复用当前筛选 + 时间范围；alarm_status 非报表维度，忽略）
function buildReportParams(): AlarmReportParams {
  return {
    start: timeRange.value?.[0] || undefined,
    end: timeRange.value?.[1] || undefined,
    project_id: filters.project_id ?? undefined,
    alarm_type: filters.alarm_type || undefined,
    handle_status: filters.handle_status || undefined,
  };
}

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* 忽略 */
  }
}

async function loadAlarms() {
  loading.value = true;
  try {
    const res = await fetchAlarms({
      project_id: filters.project_id ?? undefined,
      alarm_type: filters.alarm_type || undefined,
      handle_status: filters.handle_status || undefined,
      alarm_status: filters.alarm_status || undefined,
      page: page.value,
      size: size.value,
    });
    list.value = res.items;
    total.value = res.total;
    void resolveAllMedia();
  } catch (e: any) {
    ElMessage.error(e?.message || "加载告警失败");
  } finally {
    loading.value = false;
    loadTrend();
  }
}

// 换页：仅重载列表（趋势图随 loadAlarms 一并刷新）
function onPageChange(p: number) {
  page.value = p;
  loadAlarms();
}

// 把当前列表里所有告警媒体的代理 URL 解析为部门隔离的预签名直连 URL
async function resolveAllMedia() {
  const urls: string[] = [];
  for (const a of list.value) {
    if (a.media_urls) urls.push(...a.media_urls);
  }
  if (!urls.length) {
    mediaSrc.value = {};
    return;
  }
  const keys = urls.map((u) => mediaKeyFromUrl(u));
  const map = await resolvePresigned(keys);
  const m: Record<string, string> = {};
  urls.forEach((u, i) => {
    m[u] = map[keys[i]] || "";
  });
  mediaSrc.value = m;
}

function onSizeChange(s: number) {
  size.value = s;
  page.value = 1;
  loadAlarms();
}

// 应用筛选：回到第 1 页再重载（避免停留在超出范围的页码）
function applyFilters() {
  page.value = 1;
  loadAlarms();
}

function resetFilters() {
  filters.project_id = null;
  filters.alarm_type = "";
  filters.handle_status = "";
  filters.alarm_status = "";
  timeRange.value = null;
  page.value = 1;
  loadAlarms();
}

// ----- 地图数据（设备实时/配置坐标 + 围栏）-----
async function loadMapData() {
  try {
    const [locRes, devRes, fenceRes] = await Promise.all([
      fetchLocations(),
      fetchDevices(),
      fetchFences({ page: 1, size: 200 }),
    ]);
    for (const l of locRes.items) {
      if (l.gcj02) liveByNo[l.device_no] = l;
    }
    const devs: MapDevice[] = [];
    for (const d of devRes.items as DeviceItem[]) {
      const live = liveByNo[d.device_no];
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
    /* 地图数据失败不阻塞告警表格 */
  }
}

// 点击告警行/定位按钮 → 地图上聚焦对应设备
function selectAlarm(row: any) {
  if (!row.device_no) return;
  selectedAlarmId.value = row.id;
  mapRef.value?.focusDevice(row.device_no);
}
function onRowClick(row: any) {
  selectAlarm(row);
}
function rowClassName({ row }: { row: any }) {
  return row.id === selectedAlarmId.value ? "alarm-row-active" : "";
}

// ----- 处置弹窗 -----
const handleVisible = ref(false);
const handling = ref(false);
const handleMedia = ref<string[]>([]);
const handleForm = reactive<{ id: number; handle_status: string; content: string }>({
  id: 0,
  handle_status: "已处理",
  content: "",
});
function openHandle(row: any) {
  handleForm.id = row.id;
  handleForm.handle_status = row.handle_status === "待处理" ? "已处理" : row.handle_status;
  handleForm.content = row.handle_content || "";
  handleMedia.value = Array.isArray(row.media_urls) ? [...row.media_urls] : [];
  handleVisible.value = true;
}
// 媒体变更即时持久化到告警（前端维护列表，后端整体替换）
async function onMediaChange(list: string[]) {
  if (!handleForm.id) return;
  try {
    await putAlarmMedia(handleForm.id, list);
  } catch (e: any) {
    ElMessage.error(e?.message || "媒体保存失败");
  }
}
function mediaType(url: string): "image" | "video" {
  const ext = (url.split("?")[0].split("#")[0].split(".").pop() || "").toLowerCase();
  if (["mp4", "webm", "mov", "avi", "mkv"].includes(ext)) return "video";
  return "image";
}
async function submitHandle() {
  handling.value = true;
  try {
    await handleAlarm(handleForm.id, {
      handle_status: handleForm.handle_status,
      content: handleForm.content || null,
    });
    ElMessage.success("处置已保存");
    handleVisible.value = false;
    loadAlarms();
  } catch (e: any) {
    ElMessage.error(e?.message || "处置失败");
  } finally {
    handling.value = false;
  }
}

// ----- 配置弹窗 -----
const configVisible = ref(false);
const configLoading = ref(false);
const configSaving = ref(false);
const configForm = reactive<AlarmConfig>({
  id: 0,
  enable_popup: true,
  enable_voice: true,
  voice_file: null,
  distance_machine: 50,
  distance_handheld: 20,
  distance_badge: 20,
  distance_band: 20,
});
async function openConfig() {
  configVisible.value = true;
  configLoading.value = true;
  try {
    const cfg = await getAlarmConfig();
    Object.assign(configForm, cfg);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载配置失败");
  } finally {
    configLoading.value = false;
  }
}
async function saveConfig() {
  configSaving.value = true;
  try {
    await updateAlarmConfig({
      enable_popup: configForm.enable_popup,
      enable_voice: configForm.enable_voice,
      voice_file: configForm.voice_file,
      distance_machine: configForm.distance_machine,
      distance_handheld: configForm.distance_handheld,
      distance_badge: configForm.distance_badge,
      distance_band: configForm.distance_band,
    });
    ElMessage.success("配置已更新");
    configVisible.value = false;
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    configSaving.value = false;
  }
}

// ----- 报表弹窗 -----
const reportVisible = ref(false);
const reportLoading = ref(false);
const exporting = ref<"" | "excel" | "pdf">("");
const report = ref<AlarmReportResult | null>(null);
// 堆叠维度：按类型 / 按级别
const trendField = ref<"by_type" | "by_level">("by_type");

const reportGranularity = ref<Granularity>("day");

async function openReport() {
  reportVisible.value = true;
  reportLoading.value = true;
  report.value = null;
  try {
    report.value = await fetchAlarmReport({ ...buildReportParams(), granularity: reportGranularity.value });
  } catch (e: any) {
    ElMessage.error(e?.message || "生成报表失败");
  } finally {
    reportLoading.value = false;
  }
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

async function doExport(fmt: "excel" | "pdf") {
  exporting.value = fmt;
  try {
    const blob = await exportAlarmReport(fmt, buildReportParams());
    const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    const ext = fmt === "excel" ? "xlsx" : "pdf";
    triggerDownload(blob, `告警报表_${ts}.${ext}`);
    ElMessage.success(`已导出 ${ext.toUpperCase()}`);
  } catch (e: any) {
    ElMessage.error(e?.message || "导出失败");
  } finally {
    exporting.value = "";
  }
}

// 下钻弹窗：导出所选周期明细（天/周/月）——传 granularity+period，
// 后端据其推导整周/整月边界，与趋势图粒度联动，导出行数==下钻明细数。
const dailyExporting = ref<"" | "excel" | "pdf">("");
async function doExportDaily(fmt: "excel" | "pdf") {
  const period = dailyDate.value;
  if (!period) return;
  const g = dailyGranularity.value;
  dailyExporting.value = fmt;
  try {
    const blob = await exportAlarmReport(fmt, {
      ...buildReportParams(),
      granularity: g,
      period,
    });
    const ext = fmt === "excel" ? "xlsx" : "pdf";
    triggerDownload(blob, `告警明细_${period}.${ext}`);
    ElMessage.success(`已导出${granularityLabel(g)}明细 ${period} (${ext.toUpperCase()})`);
  } catch (e: any) {
    ElMessage.error(e?.message || "导出失败");
  } finally {
    dailyExporting.value = "";
  }
}

// ----- 主视图 live 趋势（随筛选/时间范围/粒度动态联动）-----
const trendByPeriod = ref<any[]>([]);
const trendLoading = ref(false);
const trendFieldLive = ref<"by_type" | "by_level">("by_type");
const trendGranularity = ref<Granularity>("day");

async function loadTrend() {
  try {
    const res = await fetchAlarmTrend({ ...buildReportParams(), granularity: trendGranularity.value });
    trendByPeriod.value = (res.summary.by_period as any[]) || [];
  } catch {
    /* 趋势刷新失败不阻塞主表格 */
  }
}
// 防抖：筛选/粒度变化后 350ms 再拉趋势，避免抖动
let trendTimer: ReturnType<typeof setTimeout> | null = null;
function scheduleTrend() {
  if (trendTimer) clearTimeout(trendTimer);
  trendTimer = setTimeout(loadTrend, 350);
}

// ----- 柱状图点击下钻：某日告警明细 -----
const dailyVisible = ref(false);
const dailyLoading = ref(false);
const dailyItems = ref<any[]>([]);
const dailyDate = ref("");
const dailyGranularity = ref<Granularity>("day");
const dailyTitle = computed(() => `${granularityLabel(dailyGranularity.value)}明细 · ${dailyDate.value}`);
async function onTrendClick(period: string) {
  // 弹窗内趋势用 reportGranularity，主视图用 trendGranularity
  const g = reportVisible.value ? reportGranularity.value : trendGranularity.value;
  dailyGranularity.value = g;
  dailyDate.value = period;
  dailyVisible.value = true;
  dailyLoading.value = true;
  dailyItems.value = [];
  try {
    // 下钻沿用当前报表筛选条件（项目/类型/处理状态/时间范围），保证与图表一致
    const res = await fetchAlarmPeriod({ granularity: g, period, ...buildReportParams() });
    dailyItems.value = res.items;
  } catch (e: any) {
    ElMessage.error(e?.message || `加载${granularityLabel(g)}明细失败`);
  } finally {
    dailyLoading.value = false;
  }
}

// 类型 key → 中文标签（明细/分布展示）
function typeLabel(t: string): string {
  return ALARM_TYPE_LABELS[t] || t;
}

// 占比小数 → 百分比文本
function pct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

// 项目汇总表合计行（告警数 / 待处理 / 已处置 求和）
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

// ----- 跨周期历史快照导出 -----
const snapshotGranularity = ref<Granularity>("week");
const snapshotStart = ref<string>("");
const snapshotEnd = ref<string>("");
const snapshotExporting = ref<"" | "excel" | "pdf">("");
// 快照预览（JSON，与导出同源）
const snapshotPreview = ref<SnapshotPreviewResult | null>(null);
const snapshotPreviewLoading = ref(false);
// 快照预览迷你图：按周期分类型堆叠的最大刻度（与 DashboardView/PDF/Excel 同源）
const snapshotTrendMax = computed(() =>
  snapTrendMaxOf(snapshotPreview.value?.periods ?? []),
);

async function doExportSnapshot(fmt: "excel" | "pdf") {
  if (!snapshotStart.value || !snapshotEnd.value) {
    ElMessage.warning("请选择历史快照的起始与结束日期");
    return;
  }
  snapshotExporting.value = fmt;
  try {
    const blob = await exportAlarmReport(fmt, {
      project_id: filters.project_id ?? undefined,
      alarm_type: filters.alarm_type || undefined,
      handle_status: filters.handle_status || undefined,
      granularity: snapshotGranularity.value,
      start: `${snapshotStart.value}T00:00:00`,
      end: `${snapshotEnd.value}T23:59:59.999999`,
      snapshot: true,
    });
    const ext = fmt === "excel" ? "xlsx" : "pdf";
    const tag = `${snapshotGranularity.value}_${snapshotStart.value}_${snapshotEnd.value}`;
    triggerDownload(blob, `告警快照_${tag}.${ext}`);
    ElMessage.success(`已导出${granularityLabel(snapshotGranularity.value)}历史快照 (${ext.toUpperCase()})`);
  } catch (e: any) {
    ElMessage.error(e?.message || "快照导出失败");
  } finally {
    snapshotExporting.value = "";
  }
}

// 渲染快照预览：概览 + 各周期分布 + 按项目汇总（确认无误后再导出）
async function doPreviewSnapshot() {
  if (!snapshotStart.value || !snapshotEnd.value) {
    ElMessage.warning("请选择历史快照的起始与结束日期");
    return;
  }
  snapshotPreviewLoading.value = true;
  try {
    const data = await fetchSnapshotPreview({
      project_id: filters.project_id ?? undefined,
      alarm_type: filters.alarm_type || undefined,
      handle_status: filters.handle_status || undefined,
      granularity: snapshotGranularity.value,
      start: `${snapshotStart.value}T00:00:00`,
      end: `${snapshotEnd.value}T23:59:59.999999`,
    });
    snapshotPreview.value = data;
  } catch (e: any) {
    ElMessage.error(e?.message || "快照预览失败");
  } finally {
    snapshotPreviewLoading.value = false;
  }
}

function levelTag(level: string | null): "" | "danger" | "warning" | "info" {
  if (level === "严重") return "danger";
  if (level === "警告") return "warning";
  if (level === "提示") return "info";
  return "";
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* 忽略 */
    }
  }
  await loadProjects();
  await loadAlarms();
  await loadMapData();
  await loadTrend();
});

// 筛选条件 / 时间范围 / 聚合粒度变化 → 趋势联动刷新（防抖）
watch([filters, timeRange, trendGranularity], scheduleTrend, { deep: true });
</script>

<template>
  <div class="page">
    <div class="bar">
      <el-form :inline="true" class="filters">
        <el-form-item label="项目">
          <el-select
            v-model="filters.project_id"
            placeholder="全部"
            clearable
            style="width: 160px"
          >
            <el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="filters.alarm_type" placeholder="全部" clearable style="width: 130px">
            <el-option label="围栏侵入" value="fence_intrusion" />
            <el-option label="间距过近" value="distance_too_close" />
            <el-option label="设备告警" value="device_alarm" />
          </el-select>
        </el-form-item>
        <el-form-item label="处理状态">
          <el-select v-model="filters.handle_status" placeholder="全部" clearable style="width: 120px">
            <el-option v-for="s in HANDLE_OPTIONS" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警状态">
          <el-select v-model="filters.alarm_status" placeholder="全部" clearable style="width: 120px">
            <el-option v-for="s in STATUS_OPTIONS" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="timeRange"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ss"
            range-separator="~"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 340px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyFilters">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
      <div class="bar-actions">
        <el-button v-if="canReport" type="success" plain @click="openReport">
          报表 / 导出
        </el-button>
        <el-button v-if="canConfig" type="warning" plain @click="openConfig">
          告警配置
        </el-button>
      </div>
    </div>

    <!-- 主视图 live 趋势：随上方筛选条件动态联动，点击柱可下钻当日明细 -->
    <el-card class="trend-card" shadow="never" v-if="canReport">
      <div class="trend-head">
        <span class="preview-title">
          告警趋势
          <span class="trend-hint">（随上方筛选条件联动 · 点击柱查看周期明细）</span>
        </span>
        <div class="trend-controls">
          <el-radio-group v-model="trendGranularity" size="small">
            <el-radio-button value="day">按天</el-radio-button>
            <el-radio-button value="week">按周</el-radio-button>
            <el-radio-button value="month">按月</el-radio-button>
          </el-radio-group>
          <el-radio-group v-model="trendFieldLive" size="small">
            <el-radio-button value="by_type">按类型</el-radio-button>
            <el-radio-button value="by_level">按级别</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div v-loading="trendLoading" class="trend-wrap">
        <DailyTrendChart
          :data="trendByPeriod"
          :field="trendFieldLive"
          :granularity="trendGranularity"
          :height="220"
          @bar-click="onTrendClick"
        />
      </div>
    </el-card>

    <div class="layout">
      <div class="main">
        <el-table :data="list" v-loading="loading" border stripe style="width: 100%"
          @row-click="onRowClick" :row-class-name="rowClassName">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ row.alarm_time || "-" }}</template>
      </el-table-column>
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag :type="levelTag(row.alarm_level)" effect="dark">
            {{ row.alarm_level || "告警" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          {{ ALARM_TYPE_LABELS[row.alarm_type] || row.alarm_type || "-" }}
        </template>
      </el-table-column>
      <el-table-column label="设备" min-width="160">
        <template #default="{ row }">
          <div>{{ row.device_name || "-" }}</div>
          <div class="sub">{{ DEVICE_TYPE_LABELS[row.device_type as keyof typeof DEVICE_TYPE_LABELS] || row.device_type }} · {{ row.device_no }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="alarm_info" label="告警信息" min-width="180" show-overflow-tooltip />
      <el-table-column label="告警状态" width="100">
        <template #default="{ row }">{{ row.alarm_status }}</template>
      </el-table-column>
      <el-table-column label="处理状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.handle_status === '待处理' ? 'danger' : 'success'" size="small">
            {{ row.handle_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="媒体" width="90">
        <template #default="{ row }">
          <el-popover
            v-if="row.media_urls && row.media_urls.length"
            placement="left"
            width="340"
            trigger="hover"
          >
            <template #reference>
              <el-button type="info" link>📎 {{ row.media_urls.length }}</el-button>
            </template>
            <div class="media-gallery">
              <img
                v-for="u in (row.media_urls || []).filter((x: string) => mediaType(x) === 'image' && mediaSrc[x])"
                :key="'i' + u"
                :src="mediaSrc[u]"
                class="g-thumb"
                alt="媒体"
              />
              <video
                v-for="u in (row.media_urls || []).filter((x: string) => mediaType(x) === 'video' && mediaSrc[x])"
                :key="'v' + u"
                :src="mediaSrc[u]"
                class="g-thumb"
                controls
                preload="metadata"
              />
            </div>
          </el-popover>
          <span v-else class="sub">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canHandle"
            type="primary"
            link
            @click="openHandle(row)"
          >
            处置
          </el-button>
          <el-button
            type="info"
            link
            :disabled="!row.device_no"
            @click="selectAlarm(row)"
          >
            定位
          </el-button>
        </template>
      </el-table-column>
      <template #empty>暂无告警</template>
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
      </div><!-- /main -->

      <div class="map-col">
        <div class="map-title">设备分布 · 点击告警行定位地图</div>
        <MapPanel
          ref="mapRef"
          :devices="mapDevices"
          :fences="mapFences"
          height="560px"
          @fence-click="onFenceClick"
        />
      </div>
    </div><!-- /layout -->

    <!-- 处置弹窗 -->
    <el-dialog v-model="handleVisible" title="处置告警" width="460px">
      <el-form label-width="88px">
        <el-form-item label="处理状态">
          <el-select v-model="handleForm.handle_status" style="width: 100%">
            <el-option v-for="s in HANDLE_OPTIONS" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="处置内容">
          <el-input
            v-model="handleForm.content"
            type="textarea"
            :rows="3"
            placeholder="处置说明（可选）"
          />
        </el-form-item>
        <el-form-item label="现场媒体">
          <MediaUpload
            v-model="handleMedia"
            :prefix="`alarms/${handleForm.id}`"
            @change="onMediaChange"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handleVisible = false">取消</el-button>
        <el-button type="primary" :loading="handling" @click="submitHandle">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 报表弹窗 -->
    <el-dialog v-model="reportVisible" title="告警报表" width="860px" top="6vh">
      <div v-loading="reportLoading" class="report-body">
        <div class="report-filters" v-if="report">{{ report.filters_desc }}</div>
        <template v-if="report">
          <!-- 概览卡片 -->
          <div class="stat-cards">
            <div class="stat-card">
              <div class="stat-num">{{ report.summary.total }}</div>
              <div class="stat-label">告警总数</div>
            </div>
            <div class="stat-card ok">
              <div class="stat-num">{{ report.summary.handled }}</div>
              <div class="stat-label">已处置</div>
            </div>
            <div class="stat-card warn">
              <div class="stat-num">{{ report.summary.pending }}</div>
              <div class="stat-label">待处理</div>
            </div>
            <div class="stat-card">
              <div class="stat-num">{{ report.summary.handle_rate }}%</div>
              <div class="stat-label">处置率</div>
            </div>
          </div>

          <!-- 分布 -->
          <div class="dist-row">
            <div class="dist-block">
              <div class="dist-title">按类型</div>
              <div
                v-for="(v, k) in report.summary.by_type"
                :key="'t' + k"
                class="dist-item"
              >
                <span>{{ typeLabel(k as string) }}</span><b>{{ v }}</b>
              </div>
              <div v-if="!Object.keys(report.summary.by_type).length" class="dist-empty">无</div>
            </div>
            <div class="dist-block">
              <div class="dist-title">按级别</div>
              <div
                v-for="(v, k) in report.summary.by_level"
                :key="'l' + k"
                class="dist-item"
              >
                <span>{{ k }}</span><b>{{ v }}</b>
              </div>
              <div v-if="!Object.keys(report.summary.by_level).length" class="dist-empty">无</div>
            </div>
            <div class="dist-block">
              <div class="dist-title">按处理状态</div>
              <div
                v-for="(v, k) in report.summary.by_handle_status"
                :key="'h' + k"
                class="dist-item"
              >
                <span>{{ k }}</span><b>{{ v }}</b>
              </div>
              <div v-if="!Object.keys(report.summary.by_handle_status).length" class="dist-empty">无</div>
            </div>
          </div>

          <!-- 明细预览 -->
          <!-- 按周期趋势柱状图（堆叠：按类型 / 按级别 / 按天周月 切换） -->
          <div class="trend-head">
            <span class="preview-title">按周期趋势</span>
            <div class="trend-controls">
              <el-radio-group v-model="reportGranularity" size="small" @change="openReport">
                <el-radio-button value="day">按天</el-radio-button>
                <el-radio-button value="week">按周</el-radio-button>
                <el-radio-button value="month">按月</el-radio-button>
              </el-radio-group>
              <el-radio-group v-model="trendField" size="small">
                <el-radio-button value="by_type">按类型</el-radio-button>
                <el-radio-button value="by_level">按级别</el-radio-button>
              </el-radio-group>
            </div>
          </div>
          <DailyTrendChart
            :data="(report.summary.by_period as any[]) || []"
            :field="trendField"
            :granularity="reportGranularity"
            :height="240"
            @bar-click="onTrendClick"
          />

          <div class="preview-title">
            明细预览（前 {{ report.items.length }} 条 / 共 {{ report.summary.total }} 条）
          </div>
          <el-table :data="report.items" border stripe size="small" max-height="300">
            <el-table-column prop="id" label="ID" width="64" />
            <el-table-column prop="alarm_time" label="时间" width="160" />
            <el-table-column label="类型" width="100">
              <template #default="{ row }">{{ typeLabel(row.alarm_type) }}</template>
            </el-table-column>
            <el-table-column prop="alarm_level" label="级别" width="72" />
            <el-table-column label="设备" min-width="140">
              <template #default="{ row }">
                {{ row.device_name || "-" }}<span class="sub"> · {{ row.device_no }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="alarm_info" label="告警信息" min-width="160" show-overflow-tooltip />
            <el-table-column prop="handle_status" label="处理状态" width="90" />
            <template #empty>该条件下暂无告警</template>
          </el-table>

          <!-- 跨周期历史快照：按所选粒度把每个周期单独成表，生成多页快照 -->
          <div class="snapshot-block">
            <div class="preview-title">跨周期历史快照（多页）</div>
            <div class="snapshot-controls">
              <el-radio-group v-model="snapshotGranularity" size="small">
                <el-radio-button value="week">按周</el-radio-button>
                <el-radio-button value="month">按月</el-radio-button>
                <el-radio-button value="day">按天</el-radio-button>
              </el-radio-group>
              <el-date-picker
                v-model="snapshotStart"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="起始日期"
                style="width: 150px"
              />
              <span class="snapshot-sep">~</span>
              <el-date-picker
                v-model="snapshotEnd"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="结束日期"
                style="width: 150px"
              />
            </div>
            <div class="snapshot-actions">
              <el-button
                type="primary"
                :loading="snapshotPreviewLoading"
                :disabled="!report || reportLoading"
                @click="doPreviewSnapshot"
              >
                预览快照
              </el-button>
              <el-button
                type="success"
                :loading="snapshotExporting === 'excel'"
                :disabled="!report || reportLoading"
                @click="doExportSnapshot('excel')"
              >
                导出快照 Excel
              </el-button>
              <el-button
                type="danger"
                :loading="snapshotExporting === 'pdf'"
                :disabled="!report || reportLoading"
                @click="doExportSnapshot('pdf')"
              >
                导出快照 PDF
              </el-button>
              <span class="snapshot-hint">
                每个{{ granularityLabel(snapshotGranularity) }}单独成表（概览 + 各周期明细 + 合并 + 项目汇总 + 按项目明细子表）
              </span>
            </div>

            <!-- 快照预览：概览 + 各周期分布 + 按项目汇总（与导出同源） -->
            <div v-if="snapshotPreview" v-loading="snapshotPreviewLoading" class="snapshot-preview">
              <div class="snapshot-preview-meta">
                <span>筛选：{{ snapshotPreview.meta.filters_desc }}</span>
                <span>生成：{{ snapshotPreview.meta.generated_at }}</span>
                <span>
                  共 {{ snapshotPreview.period_keys.length }} 个{{
                    granularityLabel(snapshotPreview.granularity as any)
                  }}周期 · 告警 {{ snapshotPreview.summary.total }} 条
                </span>
              </div>

              <!-- 概览指标 -->
              <div class="stat-cards mini">
                <div class="stat-card">
                  <div class="stat-num">{{ snapshotPreview.summary.total }}</div>
                  <div class="stat-label">告警总数</div>
                </div>
                <div class="stat-card ok">
                  <div class="stat-num">{{ snapshotPreview.summary.handled }}</div>
                  <div class="stat-label">已处置</div>
                </div>
                <div class="stat-card warn">
                  <div class="stat-num">{{ snapshotPreview.summary.pending }}</div>
                  <div class="stat-label">待处理</div>
                </div>
                <div class="stat-card">
                  <div class="stat-num">{{ (snapshotPreview.summary.handle_rate * 100).toFixed(1) }}%</div>
                  <div class="stat-label">处置率</div>
                </div>
              </div>

              <!-- 迷你趋势图：按周期柱状图 · 按类型分色堆叠（与 PDF/Excel 同源） -->
              <div class="preview-title">
                预览趋势（按周期 · 按类型堆叠）
                <span class="preview-title-sub">共 {{ snapshotPreview.periods.length }} 个周期</span>
              </div>
              <div class="mini-legend">
                <span><i style="background:#C00000" />围栏侵入</span>
                <span><i style="background:#ED7D31" />间距过近</span>
                <span><i style="background:#2E75B6" />设备自报</span>
              </div>
              <div class="mini-trend">
                <div
                  v-for="x in snapshotPreview.periods"
                  :key="x.period"
                  class="bar-row"
                >
                  <span class="bar-label">{{
                    formatPeriodLabel(x.period, snapshotPreview.granularity as any)
                  }}</span>
                  <div class="bar-track stack">
                    <div
                      class="bar-seg"
                      :style="{
                        width: (tc(x.by_type, 'fence_intrusion') / snapshotTrendMax * 100) + '%',
                        background: '#C00000',
                      }"
                      :title="'围栏侵入 ' + tc(x.by_type, 'fence_intrusion')"
                    />
                    <div
                      class="bar-seg"
                      :style="{
                        width: (tc(x.by_type, 'distance_too_close') / snapshotTrendMax * 100) + '%',
                        background: '#ED7D31',
                      }"
                      :title="'间距过近 ' + tc(x.by_type, 'distance_too_close')"
                    />
                    <div
                      class="bar-seg"
                      :style="{
                        width: (tc(x.by_type, 'device_alarm') / snapshotTrendMax * 100) + '%',
                        background: '#2E75B6',
                      }"
                      :title="'设备自报 ' + tc(x.by_type, 'device_alarm')"
                    />
                  </div>
                  <span class="bar-val">{{ x.total }}</span>
                </div>
                <el-empty
                  v-if="snapshotPreview.periods.length === 0"
                  description="该时间范围内暂无告警"
                  :image-size="40"
                />
              </div>

              <!-- 各周期分布（可展开看按项目拆分） -->
              <div class="preview-title">各周期告警分布</div>
              <el-table :data="snapshotPreview.periods" border stripe size="small" max-height="320">
                <el-table-column type="expand">
                  <template #default="{ row }">
                    <el-table
                      :data="row.by_project"
                      border
                      size="small"
                      style="width: 100%"
                    >
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
                :data="snapshotPreview.project_summary"
                border
                stripe
                size="small"
                max-height="320"
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

              <!-- 按项目明细（与 Excel 分 sheet / PDF 分节同源） -->
              <div class="preview-title">按项目明细（跨整个窗口，每项目一张子表）</div>
              <el-collapse
                v-if="snapshotPreview.projects_detail && snapshotPreview.projects_detail.length"
                class="proj-detail-collapse"
              >
                <el-collapse-item
                  v-for="pd in snapshotPreview.projects_detail"
                  :key="pd.project_name"
                  :name="pd.project_name"
                >
                  <template #title>
                    <span class="proj-detail-title">{{ pd.project_name }}</span>
                    <span class="proj-detail-count">
                      {{ pd.count }} 条{{ pd.capped ? "（预览截断，导出文件含完整明细）" : "" }}
                    </span>
                  </template>
                  <el-table :data="pd.rows" border stripe size="small" max-height="340">
                    <el-table-column prop="period" label="周期" width="110" />
                    <el-table-column prop="id" label="ID" width="64" />
                    <el-table-column prop="alarm_time" label="时间" width="160" />
                    <el-table-column prop="alarm_type" label="类型" width="100" />
                    <el-table-column label="级别" width="72">
                      <template #default="{ row }">
                        <el-tag :type="levelTag(row.alarm_level)" effect="dark">{{ row.alarm_level }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column prop="device_no" label="设备编号" width="130" />
                    <el-table-column prop="device_name" label="设备名称" width="120" />
                    <el-table-column prop="fence_name" label="关联围栏" width="130" />
                    <el-table-column
                      prop="alarm_info"
                      label="告警内容"
                      min-width="180"
                      show-overflow-tooltip
                    />
                    <el-table-column prop="handle_status" label="处置状态" width="100" />
                  </el-table>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="reportVisible = false">关闭</el-button>
        <el-button
          type="success"
          :loading="exporting === 'excel'"
          :disabled="!report || reportLoading"
          @click="doExport('excel')"
        >
          导出 Excel
        </el-button>
        <el-button
          type="danger"
          :loading="exporting === 'pdf'"
          :disabled="!report || reportLoading"
          @click="doExport('pdf')"
        >
          导出 PDF
        </el-button>
      </template>
    </el-dialog>

    <!-- 当日明细下钻弹窗（柱状图点击某天触发） -->
    <el-dialog v-model="dailyVisible" :title="dailyTitle" width="860px" top="6vh">
      <div v-loading="dailyLoading" class="report-body">
        <div class="report-filters" v-if="dailyItems.length">
          共 {{ dailyItems.length }} 条（沿用当前筛选条件）
        </div>
        <el-table :data="dailyItems" border stripe size="small" max-height="420">
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column prop="alarm_time" label="时间" width="160" />
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ typeLabel(row.alarm_type) }}</template>
          </el-table-column>
          <el-table-column prop="alarm_level" label="级别" width="72">
            <template #default="{ row }">
              <el-tag :type="levelTag(row.alarm_level)" effect="dark">{{ row.alarm_level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="设备" min-width="140">
            <template #default="{ row }">
              {{ row.device_name || "-" }}<span class="sub"> · {{ row.device_no }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="alarm_info" label="告警信息" min-width="160" show-overflow-tooltip />
          <el-table-column prop="handle_status" label="处理状态" width="90" />
          <template #empty>该{{ granularityLabel(dailyGranularity) }}暂无符合筛选条件的告警</template>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="dailyVisible = false">关闭</el-button>
        <el-button
          type="success"
          :loading="dailyExporting === 'excel'"
          :disabled="!dailyItems.length"
          @click="doExportDaily('excel')"
        >
          导出本{{ granularityLabel(dailyGranularity) }} Excel
        </el-button>
        <el-button
          type="danger"
          :loading="dailyExporting === 'pdf'"
          :disabled="!dailyItems.length"
          @click="doExportDaily('pdf')"
        >
          导出本{{ granularityLabel(dailyGranularity) }} PDF
        </el-button>
      </template>
    </el-dialog>

    <!-- 配置弹窗 -->
    <el-dialog v-model="configVisible" title="告警配置" width="480px">
      <el-form v-loading="configLoading" label-width="120px">
        <el-form-item label="弹窗提醒">
          <el-switch v-model="configForm.enable_popup" />
        </el-form-item>
        <el-form-item label="语音提醒">
          <el-switch v-model="configForm.enable_voice" />
        </el-form-item>
        <el-form-item label="大机告警间距">
          <el-input-number v-model="configForm.distance_machine" :min="0" :max="1000" />
          <span class="unit">米</span>
        </el-form-item>
        <el-form-item label="手持机告警间距">
          <el-input-number v-model="configForm.distance_handheld" :min="0" :max="1000" />
          <span class="unit">米</span>
        </el-form-item>
        <el-form-item label="工牌告警间距">
          <el-input-number v-model="configForm.distance_badge" :min="0" :max="1000" />
          <span class="unit">米</span>
        </el-form-item>
        <el-form-item label="手环告警间距">
          <el-input-number v-model="configForm.distance_band" :min="0" :max="1000" />
          <span class="unit">米</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="saveConfig">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 围栏点击 → 关联作业计划详情 -->
    <WorkPlanPopup
      v-model="planPopup.visible"
      :fence-id="planPopup.fenceId"
      :fence-name="planPopup.fenceName"
    />
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.filters { flex-wrap: wrap; }
.sub { color: #909399; font-size: 12px; }
.layout { display: flex; gap: 16px; align-items: flex-start; }
.main { flex: 1; min-width: 0; }
.map-col {
  width: 440px;
  flex-shrink: 0;
  position: sticky;
  top: 16px;
}
.map-title {
  font-size: 13px;
  font-weight: 600;
  color: #4a5568;
  margin-bottom: 8px;
}
.pager {
  margin-top: 12px;
  color: #606266;
  font-size: 13px;
}
.unit { margin-left: 8px; color: #909399; font-size: 12px; }
.media-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 6px;
}
.g-thumb {
  width: 100%;
  height: 96px;
  object-fit: cover;
  border-radius: 4px;
  background: #000;
}
:deep(.alarm-row-active) > td {
  background: #f0f7ff !important;
}
:deep(.alarm-row-active:hover) > td {
  background: #e3efff !important;
}
.bar-actions { display: flex; gap: 8px; flex-shrink: 0; }
.report-body { min-height: 120px; }
.report-filters {
  font-size: 12px;
  color: #909399;
  margin-bottom: 12px;
}
.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 14px 12px;
  text-align: center;
}
.stat-card.ok { background: #f0f9eb; border-color: #e1f3d8; }
.stat-card.warn { background: #fef0f0; border-color: #fde2e2; }
.stat-num { font-size: 24px; font-weight: 700; color: #303133; }
.stat-card.ok .stat-num { color: #67c23a; }
.stat-card.warn .stat-num { color: #f56c6c; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.dist-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.dist-block {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
}
.dist-title { font-size: 13px; font-weight: 600; color: #4a5568; margin-bottom: 8px; }
.dist-item {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #606266;
  padding: 3px 0;
}
.dist-item b { color: #303133; }
.dist-empty { font-size: 12px; color: #c0c4cc; }
.preview-title {
  font-size: 13px;
  font-weight: 600;
  color: #4a5568;
  margin-bottom: 8px;
}
.trend-card { margin-bottom: 12px; }
.trend-hint { font-size: 12px; color: #909399; font-weight: 400; }
.trend-wrap { min-height: 120px; }
.trend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.trend-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.trend-head .preview-title { margin-bottom: 0; }
.snapshot-block {
  margin-top: 18px;
  padding: 14px 16px;
  border: 1px dashed #c0c4cc;
  border-radius: 6px;
  background: #fafafa;
}
.snapshot-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 10px 0;
}
.snapshot-sep { color: #909399; font-size: 13px; }
.snapshot-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.snapshot-hint { font-size: 12px; color: #909399; }

/* 快照预览：按项目明细（与 Excel 分 sheet / PDF 分节同源） */
.proj-detail-collapse { margin-top: 8px; }
.proj-detail-title { font-weight: 600; margin-right: 10px; }
.proj-detail-count { font-size: 12px; color: #909399; font-weight: 400; }

/* 快照预览：概览 + 各周期分布 + 按项目汇总 */
.snapshot-preview { margin-top: 14px; border-top: 1px solid #ebeef5; padding-top: 14px; }
.snapshot-preview-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 12px;
}
.stat-cards.mini { grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.stat-cards.mini .stat-card { padding: 10px 8px; }
.stat-cards.mini .stat-num { font-size: 20px; }
.sub-chip {
  display: inline-block;
  font-size: 12px;
  color: #606266;
  background: #f0f2f5;
  border-radius: 4px;
  padding: 1px 6px;
  margin: 0 4px 4px 0;
}

/* 快照预览迷你图：按类型分色堆叠（与 DashboardView/PDF/Excel 同源） */
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
.mini-trend {
  margin-bottom: 14px;
}
.preview-title-sub {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
  margin-left: 6px;
}
</style>
