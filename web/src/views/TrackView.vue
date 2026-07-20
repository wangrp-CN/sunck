<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  VideoPause,
  VideoPlay,
  RefreshLeft,
  DArrowLeft,
  DArrowRight,
} from "@element-plus/icons-vue";
import { fetchDevices, fetchTrajectory, type DeviceItem } from "@/api/realtime";
import MapPanel from "@/components/MapPanel.vue";
import type { TrajectoryPoint } from "@/types";

const mapRef = ref<any>(null);

const devices = ref<DeviceItem[]>([]);
const deviceNo = ref("");
const timeRange = ref<[Date, Date] | null>(null);
const points = ref<TrajectoryPoint[]>([]);
const coords = ref<[number, number][]>([]);
const times = ref<number[]>([]);

const loading = ref(false);
const playing = ref(false);
const speed = ref(1);
const progress = ref(0);
const currentTime = ref("");

const durationMs = computed(() =>
  times.value.length > 1 ? times.value[times.value.length - 1] - times.value[0] : 0,
);
const startTimeStr = computed(() => (times.value.length ? fmt(times.value[0]) : "—"));
const endTimeStr = computed(() =>
  times.value.length ? fmt(times.value[times.value.length - 1]) : "—",
);

// 当前帧（距 playMs 最近的离散轨迹点）
const currentIndex = computed(() => {
  const t = times.value;
  if (t.length === 0) return -1;
  const ms = t[0] + playMs;
  let idx = 0;
  let best = Infinity;
  for (let i = 0; i < t.length; i++) {
    const d = Math.abs(t[i] - ms);
    if (d < best) {
      best = d;
      idx = i;
    }
  }
  return idx;
});
const currentPoint = computed<TrajectoryPoint | null>(() => {
  const i = currentIndex.value;
  return i >= 0 && i < points.value.length ? points.value[i] : null;
});
const frameLabel = computed(() =>
  currentIndex.value >= 0 ? `${currentIndex.value + 1} / ${points.value.length}` : "—",
);

let rafId = 0;
let lastTs = 0;
let playMs = 0;

function pad(n: number): string {
  return n < 10 ? "0" + n : "" + n;
}
function fmt(ms: number): string {
  if (!ms) return "—";
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}:${pad(d.getSeconds())}`;
}
function toIso(d: Date): string {
  return d.toISOString();
}
function fmtCoord(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(6);
}

function positionAt(ms: number): [number, number] | null {
  const c = coords.value;
  const t = times.value;
  if (c.length === 0) return null;
  if (ms <= t[0]) return c[0];
  if (ms >= t[t.length - 1]) return c[c.length - 1];
  let lo = 0;
  let hi = t.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (t[mid] <= ms) lo = mid;
    else hi = mid;
  }
  const span = t[hi] - t[lo] || 1;
  const f = (ms - t[lo]) / span;
  return [c[lo][0] + (c[hi][0] - c[lo][0]) * f, c[lo][1] + (c[hi][1] - c[lo][1]) * f];
}

function updateMarker(ms: number) {
  const pos = positionAt(ms);
  if (pos) mapRef.value?.setMovingMarker(pos);
  currentTime.value = fmt(times.value[0] + ms);
}

function loop() {
  if (!playing.value) return;
  const now = performance.now();
  const dt = now - lastTs;
  lastTs = now;
  playMs += dt * speed.value;
  if (playMs >= durationMs.value) {
    playMs = durationMs.value;
    progress.value = 100;
    updateMarker(playMs);
    pause();
    return;
  }
  progress.value = (playMs / durationMs.value) * 100;
  updateMarker(playMs);
  rafId = requestAnimationFrame(loop);
}

function play() {
  if (points.value.length === 0) {
    ElMessage.warning("请先查询轨迹");
    return;
  }
  if (durationMs.value <= 0) {
    ElMessage.warning("该时间段内无轨迹点");
    return;
  }
  if (progress.value >= 100) progress.value = 0;
  playing.value = true;
  lastTs = performance.now();
  playMs = (progress.value / 100) * durationMs.value;
  loop();
}

function pause() {
  playing.value = false;
  cancelAnimationFrame(rafId);
}

function onScrub() {
  if (durationMs.value <= 0) return;
  playMs = (progress.value / 100) * durationMs.value;
  updateMarker(playMs);
}

function reset() {
  pause();
  progress.value = 0;
  playMs = 0;
  currentTime.value = "";
  mapRef.value?.removeMovingMarker();
}

// 逐帧：跳到上一/下一个离散轨迹点
function stepFrame(delta: number) {
  pause();
  if (points.value.length === 0) return;
  let idx = currentIndex.value;
  if (idx < 0) idx = 0;
  idx = Math.min(points.value.length - 1, Math.max(0, idx + delta));
  seekToIndex(idx);
}

// 跳到指定索引的离散点
function seekToIndex(idx: number) {
  pause();
  const t = times.value;
  if (idx < 0 || idx >= t.length) return;
  playMs = t[idx] - t[0];
  progress.value = durationMs.value ? (playMs / durationMs.value) * 100 : 0;
  updateMarker(playMs);
}

// 点击表格行 → 跳转到该轨迹点
function onRowClick(row: TrajectoryPoint) {
  const idx = points.value.indexOf(row);
  if (idx >= 0) seekToIndex(idx);
}

// 高亮当前帧所在的表格行
function rowClassName(data: { row: TrajectoryPoint }): string {
  return data.row === currentPoint.value ? "cur-row" : "";
}

async function query() {
  if (!deviceNo.value) {
    ElMessage.warning("请选择设备");
    return;
  }
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.warning("请选择时间范围");
    return;
  }
  loading.value = true;
  try {
    const [s, e] = timeRange.value;
    const res = await fetchTrajectory({
      device_no: deviceNo.value,
      start: toIso(s),
      end: toIso(e),
    });
    const items = res.items.filter((p) => p.gcj02);
    points.value = items;
    coords.value = items.map((p) => [p.gcj02!.lng, p.gcj02!.lat] as [number, number]);
    times.value = items.map((p) => new Date(p.report_time!).getTime());
    progress.value = 0;
    playMs = 0;
    currentTime.value = "";
    await nextTick();
    if (coords.value.length) {
      mapRef.value?.setTrajectory(coords.value);
      mapRef.value?.setMovingMarker(coords.value[0]);
    } else {
      mapRef.value?.clearTrajectory();
      ElMessage.info("该时间段内无轨迹数据");
    }
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false;
  }
}

function onMapReady() {
  if (coords.value.length) mapRef.value?.setTrajectory(coords.value);
}

function setPreset(hours: number) {
  const end = new Date();
  const start = new Date(end.getTime() - hours * 3600 * 1000);
  timeRange.value = [start, end];
}

onMounted(async () => {
  setPreset(24);
  try {
    const res = await fetchDevices();
    devices.value = res.items;
  } catch {
    // 拦截器已提示
  }
});

onBeforeUnmount(() => cancelAnimationFrame(rafId));
</script>

<template>
  <div class="track">
    <!-- 查询条 -->
    <el-card shadow="never" class="bar-card">
      <div class="bar">
        <span class="bar-label">设备</span>
        <el-select v-model="deviceNo" placeholder="选择设备" filterable clearable style="width: 240px">
          <el-option
            v-for="d in devices"
            :key="d.device_no"
            :label="`${d.name}（${d.device_no}）`"
            :value="d.device_no"
          />
        </el-select>

        <span class="bar-label">时间范围</span>
        <el-date-picker
          v-model="timeRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          :clearable="false"
        />
        <el-button-group class="presets">
          <el-button size="small" @click="setPreset(1)">近1小时</el-button>
          <el-button size="small" @click="setPreset(6)">近6小时</el-button>
          <el-button size="small" @click="setPreset(24)">近24小时</el-button>
        </el-button-group>

        <el-button type="primary" :loading="loading" @click="query">查询轨迹</el-button>
      </div>
    </el-card>

    <!-- 播放控制条 -->
    <el-card shadow="never" class="ctrl-card">
      <div class="ctrl">
        <el-button circle @click="playing ? pause() : play()">
          <el-icon v-if="playing"><VideoPause /></el-icon>
          <el-icon v-else><VideoPlay /></el-icon>
        </el-button>
        <el-button circle title="重置" @click="reset">
          <el-icon><RefreshLeft /></el-icon>
        </el-button>
        <el-button circle title="上一帧" :disabled="points.length === 0" @click="stepFrame(-1)">
          <el-icon><DArrowLeft /></el-icon>
        </el-button>
        <el-button circle title="下一帧" :disabled="points.length === 0" @click="stepFrame(1)">
          <el-icon><DArrowRight /></el-icon>
        </el-button>
        <span class="speed-label">倍速</span>
        <el-select v-model="speed" style="width: 90px">
          <el-option :value="1" label="1x" />
          <el-option :value="2" label="2x" />
          <el-option :value="4" label="4x" />
          <el-option :value="8" label="8x" />
        </el-select>
        <span class="frame-now">帧 {{ frameLabel }}</span>
        <span class="time-now">{{ currentTime || startTimeStr }}</span>
        <el-slider
          v-model="progress"
          class="slider"
          :min="0"
          :max="100"
          :step="0.1"
          :disabled="points.length === 0"
          @input="onScrub"
        />
        <span class="time-end">{{ endTimeStr }}</span>
        <span class="count">共 {{ points.length }} 个点</span>
      </div>
    </el-card>

    <!-- 地图 / 轨迹 + 当前点信息 / 轨迹点列表 -->
    <el-row :gutter="12">
      <el-col :span="15">
        <el-card shadow="never" class="map-card">
          <template #header><span class="card-title">轨迹回放</span></template>
          <MapPanel ref="mapRef" :devices="[]" :fences="[]" height="460px" @ready="onMapReady" />
          <el-empty v-if="!loading && points.length === 0" description="暂无轨迹，请选择设备与时间范围查询" />
        </el-card>
      </el-col>

      <el-col :span="9">
        <!-- 当前帧信息 -->
        <el-card shadow="never" class="info-card">
          <template #header><span class="card-title">当前轨迹点</span></template>
          <div v-if="currentPoint" class="info">
            <div class="info-row"><span class="k">时间</span><span class="v">{{ currentPoint.report_time?.replace("T", " ") }}</span></div>
            <div class="info-row"><span class="k">速度</span><span class="v">{{ currentPoint.speed != null ? currentPoint.speed + " km/h" : "—" }}</span></div>
            <div class="info-row"><span class="k">状态</span><span class="v">{{ currentPoint.status || "—" }}</span></div>
            <div class="info-row"><span class="k">GCJ-02</span><span class="v">{{ fmtCoord(currentPoint.gcj02?.lng) }}, {{ fmtCoord(currentPoint.gcj02?.lat) }}</span></div>
            <div class="info-row"><span class="k">WGS-84</span><span class="v">{{ fmtCoord(currentPoint.longitude) }}, {{ fmtCoord(currentPoint.latitude) }}</span></div>
          </div>
          <el-empty v-else description="查询后显示" :image-size="48" />
        </el-card>

        <!-- 轨迹点列表 -->
        <el-card shadow="never" class="list-card">
          <template #header><span class="card-title">轨迹点列表（点击跳转）</span></template>
          <el-table
            v-loading="loading"
            :data="points"
            border
            stripe
            height="300"
            highlight-current-row
            :row-class-name="rowClassName"
            class="list"
            @row-click="onRowClick"
          >
            <el-table-column type="index" label="#" width="48" />
            <el-table-column label="时间" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ (row.report_time || "").replace("T", " ") }}</template>
            </el-table-column>
            <el-table-column label="速度" width="90">
              <template #default="{ row }">{{ row.speed != null ? row.speed : "—" }}</template>
            </el-table-column>
            <el-table-column label="状态" min-width="90" show-overflow-tooltip>
              <template #default="{ row }">{{ row.status || "—" }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.track {
  padding: 8px;
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
.presets {
  margin-left: 4px;
}
.ctrl-card {
  margin-bottom: 12px;
}
.ctrl {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.speed-label {
  font-size: 13px;
  color: #606266;
  margin-left: 4px;
}
.frame-now {
  font-size: 12px;
  color: #409eff;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  min-width: 64px;
  text-align: center;
}
.time-now,
.time-end {
  font-size: 12px;
  color: #303133;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.time-end {
  color: #909399;
}
.slider {
  flex: 1;
  margin: 0 8px;
  min-width: 160px;
}
.count {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.map-card {
  margin-bottom: 12px;
}
.card-title {
  font-weight: 600;
}
.info-card,
.list-card {
  margin-bottom: 12px;
}
.info {
  font-size: 13px;
}
.info-row {
  display: flex;
  padding: 6px 0;
  border-bottom: 1px dashed #f0f2f5;
}
.info-row:last-child {
  border-bottom: none;
}
.info-row .k {
  width: 64px;
  color: #909399;
  flex-shrink: 0;
}
.info-row .v {
  color: #303133;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}
.list {
  width: 100%;
}
:deep(.cur-row) {
  background: #ecf5ff !important;
}
:deep(.cur-row:hover) {
  background: #d9ecff !important;
}
</style>
