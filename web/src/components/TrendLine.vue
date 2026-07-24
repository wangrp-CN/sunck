<script setup lang="ts">
import { computed } from "vue";

// 轻量趋势线（sparkline）：不引图表库，纯内联 SVG（viewBox 自适应宽度）。
// 用于项目风险指数 / 设备健康分的时间序列迷你可视化。
interface Point {
  t: string; // 时间点（ISO 字符串）
  v: number; // 数值
}

const props = withDefaults(
  defineProps<{
    points: Point[];
    height?: number;
    width?: number;
    min?: number;
    max?: number;
    color?: string;
    threshold?: number; // 可选阈值虚线（如风险预警 60）
    showArea?: boolean;
    valueDigits?: number;
  }>(),
  { height: 40, width: 140, color: "#409eff", showArea: true, valueDigits: 0 },
);

const PAD = { top: 6, right: 6, bottom: 6, left: 6 };

const W = computed(() => props.width);
const H = computed(() => props.height);
const innerW = computed(() => Math.max(1, W.value - PAD.left - PAD.right));
const innerH = computed(() => Math.max(1, H.value - PAD.top - PAD.bottom));

const values = computed(() => props.points.map((p) => p.v));
const dataMin = computed(() => (values.value.length ? Math.min(...values.value) : 0));
const dataMax = computed(() => (values.value.length ? Math.max(...values.value) : 1));

// Y 轴范围：默认从 0 起（分值为 0-100），并容纳阈值线
const lo = computed(() => {
  if (props.min !== undefined) return props.min;
  return Math.min(0, dataMin.value, props.threshold ?? 0);
});
const hi = computed(() => {
  if (props.max !== undefined) return props.max;
  return Math.max(dataMax.value, props.threshold ?? dataMax.value, 1);
});
const span = computed(() => Math.max(1e-6, hi.value - lo.value));

function xAt(i: number): number {
  const n = props.points.length;
  if (n <= 1) return PAD.left + innerW.value / 2;
  return PAD.left + (innerW.value * i) / (n - 1);
}
function yAt(v: number): number {
  return PAD.top + innerH.value - ((v - lo.value) / span.value) * innerH.value;
}

const linePath = computed(() => {
  if (!props.points.length) return "";
  return props.points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(2)},${yAt(p.v).toFixed(2)}`)
    .join(" ");
});

const areaPath = computed(() => {
  if (!props.points.length || !props.showArea) return "";
  const base = PAD.top + innerH.value;
  const head = `M${xAt(0).toFixed(2)},${base.toFixed(2)}`;
  const body = props.points
    .map((p, i) => `L${xAt(i).toFixed(2)},${yAt(p.v).toFixed(2)}`)
    .join(" ");
  const tail = `L${xAt(props.points.length - 1).toFixed(2)},${base.toFixed(2)} Z`;
  return `${head} ${body} ${tail}`;
});

const thresholdY = computed(() =>
  props.threshold === undefined ? null : yAt(props.threshold),
);

const last = computed(() => {
  const n = props.points.length;
  if (!n) return null;
  return { x: xAt(n - 1), y: yAt(props.points[n - 1].v), p: props.points[n - 1] };
});

function fmtDate(t: string): string {
  // ISO "2026-07-24T..." → "07-24"；含时间则补 "07-24 12:30"
  if (!t) return "—";
  const d = t.slice(5, 10);
  const tm = t.length >= 16 ? t.slice(11, 16) : "";
  return tm ? `${d} ${tm}` : d;
}
function fmtVal(v: number): string {
  return v.toFixed(props.valueDigits);
}

const hasData = computed(() => props.points.length > 0);
const gradientId = computed(
  () => `tl-grad-${Math.random().toString(36).slice(2, 8)}`,
);
const ariaLabel = computed(() =>
  hasData.value
    ? `趋势：${props.points.length} 个数据点，最新值 ${fmtVal(last.value!.p.v)}`
    : "暂无趋势数据",
);
</script>

<template>
  <svg
    v-if="hasData"
    :viewBox="`0 0 ${W} ${H}`"
    :width="W"
    :height="H"
    preserveAspectRatio="none"
    role="img"
    :aria-label="ariaLabel"
    class="trend-line"
  >
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.28" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>

    <!-- 阈值虚线 -->
    <line
      v-if="thresholdY !== null"
      :x1="PAD.left"
      :x2="W - PAD.right"
      :y1="thresholdY"
      :y2="thresholdY"
      class="threshold"
    />

    <!-- 面积 -->
    <path v-if="showArea && areaPath" :d="areaPath" :fill="`url(#${gradientId})`" />

    <!-- 折线 -->
    <path :d="linePath" fill="none" :stroke="color" stroke-width="1.6" class="line" />

    <!-- 末点标记 -->
    <circle
      v-if="last"
      :cx="last.x"
      :cy="last.y"
      r="2.4"
      :fill="color"
      class="last-dot"
    />

    <!-- 逐点悬浮提示 -->
    <g v-for="(p, i) in points" :key="i">
      <circle :cx="xAt(i)" :cy="yAt(p.v)" r="6" fill="transparent" class="hit">
        <title>{{ fmtDate(p.t) }} · {{ fmtVal(p.v) }}</title>
      </circle>
    </g>
  </svg>
  <span v-else class="tl-empty">—</span>
</template>

<style scoped>
.trend-line {
  display: block;
}
.threshold {
  stroke: #f56c6c;
  stroke-width: 1;
  stroke-dasharray: 3 3;
  opacity: 0.7;
}
.line {
  stroke-linejoin: round;
  stroke-linecap: round;
}
.last-dot {
  stroke: #fff;
  stroke-width: 1;
}
.hit {
  pointer-events: all;
  cursor: pointer;
}
.tl-empty {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
