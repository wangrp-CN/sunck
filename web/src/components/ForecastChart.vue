<script setup lang="ts">
import { computed } from "vue";
import type { ForecastContribution, ForecastFit, ForecastSeriesPoint } from "@/api/forecast";

// 预测图（Phase 5 M4 驾驶舱预测卡）：纯内联 SVG，不引图表库。
// 历史实线 + 预测虚线延伸 + 预测点 + 95% 置信带（从末点张开到预测点的扇形区）
// + 阈值虚线。x 轴按真实时间戳比例布点（历史与预测跨度按时长占位）。
// 另含「特征贡献归因」横向条形图（可解释化）：各外部/日历特征对预测值的贡献（按 |impact| 降序）。
const props = withDefaults(
  defineProps<{
    series: ForecastSeriesPoint[];
    forecast: ForecastFit | null;
    threshold?: number; // 阈值虚线（risk 高=60 / health 中=60）
    width?: number;
    height?: number;
    color?: string;
    forecastColor?: string;
    contributions?: ForecastContribution[] | null;
  }>(),
  { width: 420, height: 150, color: "#409eff", forecastColor: "#e6a23c" },
);

// ---- 特征贡献归因条形图（可解释化）----
const CONTRIB_ROW_H = 18;
const CONTRIB_PAD_L = 8;
const CONTRIB_LABEL_W = 60;
const CONTRIB_VALUE_W = 40;

const showContrib = computed(() => (props.contributions?.length ?? 0) > 0);

// 排除截距基线项，最多展示前 6 个显著特征
const contribRows = computed(() =>
  (props.contributions ?? [])
    .filter((c) => c.feature !== "intercept")
    .slice(0, 6),
);

const contribW = computed(() => props.width);
const contribH = computed(() => Math.max(1, contribRows.value.length * CONTRIB_ROW_H + 8));
const contribAreaW = computed(
  () => contribW.value - CONTRIB_PAD_L - CONTRIB_LABEL_W - CONTRIB_VALUE_W - 4,
);
const contribCenterX = computed(() => CONTRIB_PAD_L + CONTRIB_LABEL_W + 4 + contribAreaW.value / 2);

const contribMaxAbs = computed(() => {
  const m = Math.max(1e-9, ...contribRows.value.map((r) => Math.abs(r.impact)));
  return m;
});

const contribBars = computed(() =>
  contribRows.value.map((r, i) => {
    const cy = 8 + i * CONTRIB_ROW_H + CONTRIB_ROW_H / 2;
    const len = (Math.abs(r.impact) / contribMaxAbs.value) * (contribAreaW.value / 2);
    const pos = r.impact >= 0;
    return {
      label: r.label,
      valueText: (pos ? "+" : "") + r.impact.toFixed(1),
      x: pos ? contribCenterX.value : contribCenterX.value - len,
      y: cy - 5,
      w: Math.max(len, 1.2),
      color: pos ? "#e6a23c" : "#409eff",
      textY: cy + 3.5,
    };
  }),
);

const PAD = { top: 14, right: 46, bottom: 20, left: 8 };

const innerW = computed(() => Math.max(1, props.width - PAD.left - PAD.right));
const innerH = computed(() => Math.max(1, props.height - PAD.top - PAD.bottom));

function ts(iso: string): number {
  return new Date(iso).getTime();
}

const hasSeries = computed(() => props.series.length > 0);

// x 时间域：历史首点 → 预测点（无预测则到历史末点）
const t0 = computed(() => (hasSeries.value ? ts(props.series[0].at) : 0));
const tEnd = computed(() => {
  if (props.forecast) return ts(props.forecast.forecast_at);
  return hasSeries.value ? ts(props.series[props.series.length - 1].at) : 1;
});
const tSpan = computed(() => Math.max(1, tEnd.value - t0.value));

// y 值域：容纳历史值 / 置信带上下界 / 阈值，默认从 0 起
const lo = computed(() => {
  let m = 0;
  for (const p of props.series) m = Math.min(m, p.value);
  if (props.forecast) m = Math.min(m, props.forecast.forecast_lower);
  return m;
});
const hi = computed(() => {
  let m = 1;
  for (const p of props.series) m = Math.max(m, p.value);
  if (props.forecast) m = Math.max(m, props.forecast.forecast_upper);
  if (props.threshold !== undefined) m = Math.max(m, props.threshold);
  return m * 1.08;
});
const span = computed(() => Math.max(1e-6, hi.value - lo.value));

function xAt(t: number): number {
  return PAD.left + ((t - t0.value) / tSpan.value) * innerW.value;
}
function yAt(v: number): number {
  return PAD.top + innerH.value - ((v - lo.value) / span.value) * innerH.value;
}

// 历史折线
const linePath = computed(() => {
  if (!hasSeries.value) return "";
  return props.series
    .map((p, i) => `${i === 0 ? "M" : "L"}${xAt(ts(p.at)).toFixed(2)},${yAt(p.value).toFixed(2)}`)
    .join(" ");
});

const lastPoint = computed(() => {
  if (!hasSeries.value) return null;
  const p = props.series[props.series.length - 1];
  return { x: xAt(ts(p.at)), y: yAt(p.value), v: p.value, t: p.at };
});

// 预测点与置信带（从历史末点张开到预测点的三角带）
const fcPoint = computed(() => {
  if (!props.forecast) return null;
  const x = xAt(ts(props.forecast.forecast_at));
  return {
    x,
    y: yAt(props.forecast.forecast_value),
    yLo: yAt(props.forecast.forecast_lower),
    yHi: yAt(props.forecast.forecast_upper),
  };
});

const bandPath = computed(() => {
  if (!lastPoint.value || !fcPoint.value) return "";
  const l = lastPoint.value;
  const f = fcPoint.value;
  return `M${l.x.toFixed(2)},${l.y.toFixed(2)} L${f.x.toFixed(2)},${f.yHi.toFixed(2)} L${f.x.toFixed(2)},${f.yLo.toFixed(2)} Z`;
});

const projPath = computed(() => {
  if (!lastPoint.value || !fcPoint.value) return "";
  return `M${lastPoint.value.x.toFixed(2)},${lastPoint.value.y.toFixed(2)} L${fcPoint.value.x.toFixed(2)},${fcPoint.value.y.toFixed(2)}`;
});

const thresholdY = computed(() =>
  props.threshold === undefined ? null : yAt(props.threshold),
);

function fmtDate(iso: string): string {
  return iso.slice(5, 10);
}

const xLabels = computed(() => {
  const out: { x: number; text: string; cls?: string }[] = [];
  if (hasSeries.value) {
    out.push({ x: xAt(t0.value), text: fmtDate(props.series[0].at) });
    const lastT = props.series[props.series.length - 1].at;
    if (props.series.length > 1) out.push({ x: xAt(ts(lastT)), text: fmtDate(lastT) });
  }
  if (props.forecast) {
    out.push({ x: xAt(ts(props.forecast.forecast_at)), text: fmtDate(props.forecast.forecast_at), cls: "fc" });
  }
  return out;
});
</script>

<template>
  <div class="forecast-chart-wrap">
    <svg
      v-if="hasSeries"
      :viewBox="`0 0 ${width} ${height}`"
      :width="width"
      :height="height"
      role="img"
      class="forecast-chart"
      :aria-label="`预测图：${series.length} 个历史点${forecast ? `，预测值 ${forecast.forecast_value}` : ''}`"
    >
      <!-- 阈值虚线 -->
      <line
        v-if="thresholdY !== null"
        :x1="PAD.left"
        :x2="width - PAD.right"
        :y1="thresholdY"
        :y2="thresholdY"
        class="fc-threshold"
      />
      <text
        v-if="thresholdY !== null"
        :x="width - PAD.right + 4"
        :y="thresholdY + 3"
        class="fc-th-label"
      >
        {{ threshold }}
      </text>

      <!-- 95% 置信带 -->
      <path v-if="bandPath" :d="bandPath" class="fc-band" :fill="forecastColor" />

      <!-- 历史折线 -->
      <path :d="linePath" fill="none" :stroke="color" stroke-width="1.8" class="fc-line" />

      <!-- 预测虚线延伸 -->
      <path
        v-if="projPath"
        :d="projPath"
        fill="none"
        :stroke="forecastColor"
        stroke-width="1.6"
        stroke-dasharray="4 3"
        class="fc-proj"
      />

      <!-- 历史末点 -->
      <circle v-if="lastPoint" :cx="lastPoint.x" :cy="lastPoint.y" r="2.6" :fill="color" class="fc-dot" />

      <!-- 预测点（菱形） + 数值标注 -->
      <g v-if="fcPoint && forecast" class="fc-point">
        <rect
          :x="fcPoint.x - 3.4"
          :y="fcPoint.y - 3.4"
          width="6.8"
          height="6.8"
          :fill="forecastColor"
          :transform="`rotate(45 ${fcPoint.x} ${fcPoint.y})`"
          stroke="#fff"
          stroke-width="1"
        />
        <text :x="fcPoint.x + 6" :y="fcPoint.y - 6" class="fc-value" :fill="forecastColor">
          {{ forecast.forecast_value.toFixed(0) }}
        </text>
        <!-- 置信带上下界刻度 -->
        <text :x="fcPoint.x + 6" :y="fcPoint.yHi + 3" class="fc-bound">{{ forecast.forecast_upper.toFixed(0) }}</text>
        <text :x="fcPoint.x + 6" :y="fcPoint.yLo + 3" class="fc-bound">{{ forecast.forecast_lower.toFixed(0) }}</text>
      </g>

      <!-- x 轴日期 -->
      <text
        v-for="(l, i) in xLabels"
        :key="i"
        :x="l.x"
        :y="height - 6"
        text-anchor="middle"
        class="fc-x-label"
        :class="l.cls"
      >
        {{ l.text }}
      </text>
    </svg>

    <!-- 特征贡献归因（可解释化）：横向发散条形图 -->
    <svg
      v-if="showContrib"
      :viewBox="`0 0 ${contribW} ${contribH}`"
      :width="contribW"
      :height="contribH"
      role="img"
      class="forecast-contrib"
      aria-label="预测特征贡献归因"
    >
      <line :x1="contribCenterX" :x2="contribCenterX" :y1="6" :y2="contribH - 4" class="fc-contrib-axis" />
      <g v-for="(b, i) in contribBars" :key="i">
        <text :x="CONTRIB_PAD_L" :y="b.textY" class="fc-contrib-label">{{ b.label }}</text>
        <rect :x="b.x" :y="b.y" :width="b.w" height="10" :fill="b.color" rx="1.5" class="fc-contrib-bar" />
        <text :x="contribW - 4" :y="b.textY" text-anchor="end" class="fc-contrib-val">{{ b.valueText }}</text>
      </g>
    </svg>

    <div v-if="!hasSeries" class="fc-empty">暂无快照序列</div>
  </div>
</template>

<style scoped>
.forecast-chart {
  display: block;
}
.fc-threshold {
  stroke: #f56c6c;
  stroke-width: 1;
  stroke-dasharray: 3 3;
  opacity: 0.7;
}
.fc-th-label {
  font-size: 9px;
  fill: #f56c6c;
}
.fc-band {
  opacity: 0.16;
}
.fc-line {
  stroke-linejoin: round;
  stroke-linecap: round;
}
.fc-dot {
  stroke: #fff;
  stroke-width: 1;
}
.fc-value {
  font-size: 11px;
  font-weight: 700;
}
.fc-bound {
  font-size: 9px;
  fill: #c0c4cc;
}
.fc-x-label {
  font-size: 9px;
  fill: #909399;
}
.fc-x-label.fc {
  fill: #e6a23c;
  font-weight: 700;
}
.fc-empty {
  color: #c0c4cc;
  font-size: 12px;
  text-align: center;
  padding: 24px 0;
}
.forecast-contrib {
  display: block;
  margin-top: 6px;
}
.fc-contrib-axis {
  stroke: #dcdfe6;
  stroke-width: 1;
}
.fc-contrib-label {
  font-size: 10px;
  fill: #606266;
}
.fc-contrib-val {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  fill: #303133;
  font-weight: 600;
}
.fc-contrib-bar {
  opacity: 0.85;
}
</style>
