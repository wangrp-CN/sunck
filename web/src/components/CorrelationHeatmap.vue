<script setup lang="ts">
import { computed } from "vue";
import type { CorrelationHeatPoint } from "@/api/metrics";

// 跨设备共因空间热力图（自包含 SVG 投影，不引任何图表/地图库）。
// 将各事件组的代表坐标（WGS-84 lng/lat）按经纬度包围盒线性投影到 SVG 画布，
// 每个点渲染为一团热力（半径/颜色随 weight=告警数映射）。与 TrendLine 一致的
// 「无图表库 + 内联 SVG」哲学：零外部依赖、无需高德 Key、可单元测试。
const props = withDefaults(
  defineProps<{
    points: CorrelationHeatPoint[];
    width?: number;
    height?: number;
  }>(),
  { width: 820, height: 360 },
);

const emit = defineEmits<{ (e: "select", p: CorrelationHeatPoint): void }>();

const PAD = 28; // 画布内边距，给热力半径留出溢出空间

const W = computed(() => props.width);
const H = computed(() => props.height);
const innerW = computed(() => Math.max(1, W.value - PAD * 2));
const innerH = computed(() => Math.max(1, H.value - PAD * 2));

const hasData = computed(() => props.points.length > 0);

// 经纬度包围盒（退化时给一个最小跨度，使单点/共线点居中显示）
const bbox = computed(() => {
  const lngs = props.points.map((p) => p.lng);
  const lats = props.points.map((p) => p.lat);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const spanLng = Math.max(maxLng - minLng, 1e-4);
  const spanLat = Math.max(maxLat - minLat, 1e-4);
  return { minLng, maxLng, minLat, maxLat, spanLng, spanLat };
});

const wMin = computed(() =>
  hasData.value ? Math.min(...props.points.map((p) => p.weight)) : 0,
);
const wMax = computed(() =>
  hasData.value ? Math.max(...props.points.map((p) => p.weight)) : 1,
);

function projX(lng: number): number {
  const { minLng, spanLng } = bbox.value;
  return PAD + ((lng - minLng) / spanLng) * innerW.value;
}
function projY(lat: number): number {
  // 纬度向北为正 → SVG y 向下，故翻转
  const { maxLat, spanLat } = bbox.value;
  return PAD + ((maxLat - lat) / spanLat) * innerH.value;
}

// weight → 强度 0..1（wMin..wMax 归一；相等时取 1）
function intensity(w: number): number {
  const lo = wMin.value;
  const hi = wMax.value;
  if (hi <= lo) return 1;
  return (w - lo) / (hi - lo);
}

// 强度分桶（0..5），用于引用预定义的 6 档热力渐变，避免逐点生成海量 defs
function bucket(w: number): number {
  return Math.min(5, Math.round(intensity(w) * 5));
}

// 半径随强度放大（弱点也可见，强点更醒目）
function radiusOf(w: number): number {
  return 14 + intensity(w) * 30;
}

// 6 档热力色（低→高：青绿 → 黄 → 橙 → 红），配合径向渐变做「热团」观感
const HEAT_COLORS = ["#2f9e8f", "#5bbf6a", "#e6c94c", "#f0a13c", "#ef6d3a", "#e23b2e"];

interface Blob {
  p: CorrelationHeatPoint;
  x: number;
  y: number;
  r: number;
  bkt: number;
  color: string;
}

const blobs = computed<Blob[]>(() =>
  // 弱点先画、强点后画（强点覆盖在上层，视觉突出）
  [...props.points]
    .sort((a, b) => a.weight - b.weight)
    .map((p) => ({
      p,
      x: projX(p.lng),
      y: projY(p.lat),
      r: radiusOf(p.weight),
      bkt: bucket(p.weight),
      color: HEAT_COLORS[bucket(p.weight)],
    })),
);

function scopeText(p: CorrelationHeatPoint): string {
  if (p.spatial_type === "fence") return p.fence_name || "围栏";
  if (p.spatial_type === "geo") return `地理网格 ${p.grid_cell ?? ""}`.trim();
  return "单机";
}

function tipText(p: CorrelationHeatPoint): string {
  const parts = [
    p.project_name || `项目#${p.project_id ?? "?"}`,
    scopeText(p),
    `告警 ${p.alarm_count} · 设备 ${p.device_count} · ${p.max_level || "—"}`,
  ];
  if (p.root_cause_hint) parts.push(p.root_cause_hint);
  return parts.join("\n");
}

// 图例刻度：显示 min/mid/max 三档权重
const legendTicks = computed(() => {
  const lo = wMin.value;
  const hi = wMax.value;
  const mid = Math.round((lo + hi) / 2);
  return { lo, mid, hi };
});
</script>

<template>
  <div class="heat-wrap">
    <svg
      v-if="hasData"
      :viewBox="`0 0 ${W} ${H}`"
      :width="'100%'"
      :height="H"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="跨设备共因空间热力图"
      class="heat-svg"
    >
      <defs>
        <radialGradient
          v-for="(c, i) in HEAT_COLORS"
          :id="`heat-g-${i}`"
          :key="i"
          cx="50%"
          cy="50%"
          r="50%"
        >
          <stop offset="0%" :stop-color="c" stop-opacity="0.78" />
          <stop offset="55%" :stop-color="c" stop-opacity="0.32" />
          <stop offset="100%" :stop-color="c" stop-opacity="0" />
        </radialGradient>
      </defs>

      <!-- 底图：浅色画布 + 参考网格，暗示空间关系（非真实地图） -->
      <rect :x="0" :y="0" :width="W" :height="H" class="canvas-bg" rx="10" />
      <g class="grid">
        <line
          v-for="gx in 8"
          :key="`vx-${gx}`"
          :x1="PAD + (innerW * gx) / 9"
          :x2="PAD + (innerW * gx) / 9"
          :y1="PAD"
          :y2="H - PAD"
        />
        <line
          v-for="gy in 4"
          :key="`hy-${gy}`"
          :x1="PAD"
          :x2="W - PAD"
          :y1="PAD + (innerH * gy) / 5"
          :y2="PAD + (innerH * gy) / 5"
        />
      </g>

      <!-- 热团 -->
      <g class="blobs">
        <g
          v-for="b in blobs"
          :key="b.p.id"
          class="blob"
          @click="emit('select', b.p)"
        >
          <circle :cx="b.x" :cy="b.y" :r="b.r" :fill="`url(#heat-g-${b.bkt})`" />
          <circle :cx="b.x" :cy="b.y" r="3.2" :fill="b.color" class="core">
            <title>{{ tipText(b.p) }}</title>
          </circle>
        </g>
      </g>
    </svg>

    <div v-if="hasData" class="legend">
      <span class="legend-label">弱</span>
      <span class="legend-bar" />
      <span class="legend-label">强</span>
      <span class="legend-ticks">
        告警数 {{ legendTicks.lo }} – {{ legendTicks.hi }}
      </span>
    </div>

    <el-empty v-if="!hasData" description="暂无空间热力数据" :image-size="48" />
  </div>
</template>

<style scoped>
.heat-wrap {
  width: 100%;
}
.heat-svg {
  display: block;
}
.canvas-bg {
  fill: #f4f7fb;
  stroke: #e4e9f2;
  stroke-width: 1;
}
.grid line {
  stroke: #e8edf5;
  stroke-width: 1;
}
.blob {
  cursor: pointer;
}
.blob .core {
  stroke: #fff;
  stroke-width: 1;
}
.legend {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}
.legend-bar {
  width: 160px;
  height: 10px;
  border-radius: 5px;
  background: linear-gradient(
    to right,
    #2f9e8f,
    #5bbf6a,
    #e6c94c,
    #f0a13c,
    #ef6d3a,
    #e23b2e
  );
}
.legend-label {
  color: #606266;
}
.legend-ticks {
  margin-left: 12px;
}
</style>
