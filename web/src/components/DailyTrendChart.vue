<script setup lang="ts">
import { computed } from "vue";
import type { Granularity } from "@/api/alarm";
import { formatPeriodLabel } from "@/utils/period";

interface DayPoint {
  date?: string;
  period?: string;
  count: number;
  by_type?: Record<string, number>;
  by_level?: Record<string, number>;
}

const props = withDefaults(
  defineProps<{
    data: DayPoint[];
    field?: "by_type" | "by_level";
    height?: number;
    granularity?: Granularity;
  }>(),
  { field: "by_type", height: 240, granularity: "day" },
);

const emit = defineEmits<{ (e: "bar-click", period: string): void }>();

type CatMap = Record<string, { label: string; color: string }>;

const TYPE_MAP: CatMap = {
  fence_intrusion: { label: "围栏侵入", color: "#f56c6c" },
  distance_too_close: { label: "间距过近", color: "#e6a23c" },
  device_alarm: { label: "设备自报", color: "#409eff" },
};
const LEVEL_MAP: CatMap = {
  严重: { label: "严重", color: "#f56c6c" },
  警告: { label: "警告", color: "#e6a23c" },
  提示: { label: "提示", color: "#409eff" },
  未分级: { label: "未分级", color: "#909399" },
};

function mapFor(field: string): CatMap {
  return field === "by_level" ? LEVEL_MAP : TYPE_MAP;
}

const PAD = { top: 16, right: 16, bottom: 34, left: 40 };

// 周期 key：优先 period（周/月），回退 date（旧按天）
function periodOf(d: DayPoint): string {
  return (d as any).period ?? d.date ?? "";
}

const sorted = computed(() =>
  [...(props.data || [])].sort((a, b) => periodOf(a).localeCompare(periodOf(b))),
);

const W = 720;
const H = computed(() => props.height);
const innerW = computed(() => W - PAD.left - PAD.right);
const innerH = computed(() => H.value - PAD.top - PAD.bottom);

// 堆叠维度下的分类集合（稳定顺序：先映射表，再补齐数据里多出的）
const cats = computed<string[]>(() => {
  const m = mapFor(props.field);
  const seen = Object.keys(m);
  const have = new Set<string>();
  const extra: string[] = [];
  for (const d of sorted.value) {
    const bd = (d as any)[props.field];
    if (bd && typeof bd === "object") {
      for (const k of Object.keys(bd)) {
        if (!have.has(k) && !m[k]) {
          have.add(k);
          extra.push(k);
        }
      }
    }
  }
  return [...seen, ...extra];
});

function dayMap(d: DayPoint): Record<string, number> {
  return ((d as any)[props.field] as Record<string, number>) || {};
}

const maxCount = computed(() => {
  let m = 1;
  for (const d of sorted.value) m = Math.max(m, d.count);
  const step = niceStep(m);
  return Math.ceil(m / step) * step;
});

function niceStep(n: number): number {
  const pow = Math.pow(10, Math.floor(Math.log10(n)));
  const f = n / pow;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return nf * pow;
}

const ticks = computed(() => {
  const step = niceStep(maxCount.value);
  const arr: number[] = [];
  for (let v = 0; v <= maxCount.value + 1e-6; v += step) arr.push(v);
  return arr;
});

const barW = computed(() => {
  const n = sorted.value.length;
  if (!n) return 0;
  return Math.max(12, innerW.value / n - 18);
});

function barX(i: number): number {
  const n = sorted.value.length;
  if (!n) return PAD.left;
  const slot = innerW.value / n;
  return PAD.left + slot * i + (slot - barW.value) / 2;
}

// 整列命中区域（透明，覆盖整列便于点击下钻）
const slotW = computed(() => (sorted.value.length ? innerW.value / sorted.value.length : 0));
function slotX(i: number): number {
  return PAD.left + slotW.value * i;
}

function barH(count: number): number {
  if (maxCount.value <= 0) return 0;
  return (count / maxCount.value) * innerH.value;
}

// X 轴标签：按粒度格式化周期 key
function axisLabel(d: DayPoint): string {
  return formatPeriodLabel(periodOf(d), props.granularity);
}

// 某天某分类的堆叠段几何（y 从下往上）
function segGeom(d: DayPoint, _i: number, cat: string): { y: number; h: number } {
  const total = d.count || 0;
  const dm = dayMap(d);
  const c = dm[cat] || 0;
  if (c <= 0) return { y: 0, h: 0 };
  // 累计到该 cat 之前的偏移
  let below = 0;
  for (const k of cats.value) {
    if (k === cat) break;
    below += dm[k] || 0;
  }
  const totalH = barH(total);
  const unit = total > 0 ? totalH / total : 0;
  const h = c * unit;
  const y = PAD.top + innerH.value - below * unit - h;
  return { y, h };
}

function catMeta(cat: string) {
  const m = mapFor(props.field);
  return m[cat] || { label: cat, color: "#909399" };
}

const ariaLabel = computed(() => {
  const g = props.granularity === "week" ? "按周" : props.granularity === "month" ? "按月" : "按天";
  return `告警${g}趋势（堆叠）`;
});
</script>

<template>
  <div class="trend">
    <!-- 图例 -->
    <div class="legend">
      <span v-for="c in cats" :key="c" class="lg">
        <i class="sw" :style="{ background: catMeta(c).color }" />
        {{ catMeta(c).label }}
      </span>
    </div>

    <svg
      :viewBox="`0 0 ${W} ${H}`"
      width="100%"
      :height="H"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      :aria-label="ariaLabel"
    >
      <!-- 网格 + Y 刻度 -->
      <g class="grid">
        <template v-for="t in ticks" :key="'t' + t">
          <line
            :x1="PAD.left"
            :x2="W - PAD.right"
            :y1="PAD.top + innerH - (t / maxCount) * innerH"
            :y2="PAD.top + innerH - (t / maxCount) * innerH"
          />
          <text
            :x="PAD.left - 8"
            :y="PAD.top + innerH - (t / maxCount) * innerH + 4"
            class="ytick"
          >
            {{ t }}
          </text>
        </template>
      </g>
      <line
        :x1="PAD.left"
        :x2="W - PAD.right"
        :y1="PAD.top + innerH"
        :y2="PAD.top + innerH"
        class="axis"
      />

      <!-- 堆叠柱子 -->
      <template v-if="sorted.length">
        <g
          v-for="(d, i) in sorted"
          :key="periodOf(d)"
          class="col"
          @click="emit('bar-click', periodOf(d))"
        >
          <!-- 整列透明命中区：点击下钻到该周期明细 -->
          <rect
            :x="slotX(i)"
            :y="PAD.top"
            :width="slotW"
            :height="innerH"
            fill="transparent"
            class="hit"
          />
          <template v-for="c in cats" :key="c">
            <rect
              v-if="(dayMap(d)[c] || 0) > 0"
              :x="barX(i)"
              :y="segGeom(d, i, c).y"
              :width="barW"
              :height="segGeom(d, i, c).h"
              :fill="catMeta(c).color"
              class="bar"
            >
              <title>
                {{ periodOf(d) }} · {{ catMeta(c).label }}：{{ dayMap(d)[c] }} 条（点击查看明细）
              </title>
            </rect>
          </template>
          <text
            v-if="d.count > 0"
            :x="barX(i) + barW / 2"
            :y="PAD.top + innerH - barH(d.count) - 5"
            class="val"
          >
            {{ d.count }}
          </text>
          <text
            :x="barX(i) + barW / 2"
            :y="PAD.top + innerH + 18"
            class="xtick"
          >
            {{ axisLabel(d) }}
          </text>
        </g>
      </template>
      <text v-else :x="W / 2" :y="H / 2" class="empty">该条件下暂无数据</text>
    </svg>
  </div>
</template>

<style scoped>
.trend { width: 100%; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 6px; }
.lg { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: #606266; }
.sw { width: 11px; height: 11px; border-radius: 2px; display: inline-block; }
.grid line { stroke: #ebeef5; stroke-width: 1; }
.axis { stroke: #c0c4cc; stroke-width: 1; }
.ytick { fill: #909399; font-size: 11px; text-anchor: end; }
.xtick { fill: #606266; font-size: 11px; text-anchor: middle; }
.val { fill: #303133; font-size: 11px; font-weight: 600; text-anchor: middle; }
.bar { transition: opacity 0.15s; }
.bar:hover { opacity: 0.82; }
.col { cursor: pointer; }
.hit { pointer-events: all; }
.empty { fill: #c0c4cc; font-size: 13px; text-anchor: middle; }
</style>
