<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getSituation, type SituationSummary } from "@/api/alarm";

// 监控大屏 · 告警态势总览卡
// 整合「今日新增 / 待处理 / 严重待处理 / 活跃预防式」KPI + 待处理按级别分布 +
// 近 N 天按级别每日堆叠趋势（内联 SVG，无图表库），点击直达告警页。
// 60s 自动刷新，不占大屏主轮询（独立定时器）。

const router = useRouter();
const loading = ref(false);
const data = ref<SituationSummary | null>(null);
let timer: number | null = null;

const LEVEL_COLORS: Record<string, string> = {
  严重: "#f56c6c",
  警告: "#e6a23c",
  提示: "#409eff",
};
const LEVEL_ORDER = ["严重", "警告", "提示"];

const kpi = computed(() => data.value?.kpi ?? null);
const pendingByLevel = computed(() =>
  Object.entries(data.value?.pending_by_level ?? {}).map(([level, count]) => ({ level, count })),
);

// ---- 内联 SVG 堆叠面积趋势（无图表库） ----
const W = 680;
const H = 160;
const PAD_X = 8;
const PAD_TOP = 12;
const PAD_BOTTOM = 18;
const innerW = W - PAD_X * 2;
const innerH = H - PAD_TOP - PAD_BOTTOM;

interface Layer {
  level: string;
  color: string;
  d: string;
}
const trendChart = computed<{
  layers: Layer[];
  labels: string[];
  showDot: boolean;
  dotCx: number;
  dotCy: number;
  dotColor: string;
}>(() => {
  const pts = data.value?.trend ?? [];
  const n = pts.length;
  if (n === 0) return { layers: [], labels: [], showDot: false, dotCx: 0, dotCy: 0, dotColor: "" };
  const xs = pts.map((_, i) => (n === 1 ? PAD_X + innerW / 2 : PAD_X + (innerW * i) / (n - 1)));
  const maxTotal = Math.max(1, ...pts.map((p) => p.total));
  const y = (v: number) => PAD_TOP + innerH * (1 - v / maxTotal);

  const band = (yHigh: number[], yLow: number[]): string => {
    if (n === 1) return "";
    let p = `M ${xs[0]},${yHigh[0]}`;
    for (let i = 1; i < n; i++) p += ` L ${xs[i]},${yHigh[i]}`;
    for (let i = n - 1; i >= 0; i--) p += ` L ${xs[i]},${yLow[i]}`;
    return p + " Z";
  };

  const layers: Layer[] = [];
  let acc = 0;
  for (const level of LEVEL_ORDER) {
    const lowerAll = pts.map(() => y(acc));
    acc += pts.reduce((s, p) => s + (Number(p[level as keyof typeof p]) || 0), 0);
    const upperAll = pts.map(() => y(acc));
    const d = band(upperAll, lowerAll);
    if (d) layers.push({ level, color: LEVEL_COLORS[level], d });
  }

  const labels =
    n <= 1
      ? [pts[0].date.slice(5)]
      : [pts[0].date.slice(5), pts[Math.floor((n - 1) / 2)].date.slice(5), pts[n - 1].date.slice(5)];

  // 单点退化：渲染一个圆点
  const showDot = n === 1;
  const last = pts[n - 1];
  const dotColor = last.total > 0 ? "#e6a23c" : "#409eff";
  return {
    layers,
    labels,
    showDot,
    dotCx: xs[0],
    dotCy: y(last.total),
    dotColor,
  };
});

const lastTotal = computed(() => {
  const t = data.value?.trend ?? [];
  return t.length ? t[t.length - 1].total : 0;
});
const trendDays = computed(() => data.value?.trend?.length ?? 14);

// 标签定位：首/中/末均分宽度（与 SVG 内 padding 对齐）
function labelStyle(i: number): Record<string, string> {
  const leftPct = i === 0 ? 0 : i === 2 ? 100 : 50;
  return {
    position: "absolute",
    left: `${leftPct}%`,
    transform: i === 2 ? "translateX(-100%)" : i === 1 ? "translateX(-50%)" : "none",
  };
}

async function load() {
  loading.value = true;
  try {
    data.value = await getSituation();
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false;
  }
}

function goDetail() {
  router.push("/alarms");
}

onMounted(() => {
  void load();
  timer = window.setInterval(() => void load(), 60000);
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
  timer = null;
});
</script>

<template>
  <el-card shadow="never" class="sit-card" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">告警态势总览</span>
        <span class="card-sub">今日新增 / 待处理 / 近 14 天趋势 · 60s 刷新</span>
      </div>
    </template>

    <!-- KPI 条 -->
    <div class="sit-kpis">
      <div class="sit-kpi">
        <div class="sit-kpi-num">{{ kpi?.today_new ?? 0 }}</div>
        <div class="sit-kpi-label">今日新增</div>
      </div>
      <div class="sit-kpi">
        <div class="sit-kpi-num">{{ kpi?.pending ?? 0 }}</div>
        <div class="sit-kpi-label">待处理</div>
      </div>
      <div class="sit-kpi" :class="{ danger: (kpi?.pending_critical ?? 0) > 0 }">
        <div class="sit-kpi-num">{{ kpi?.pending_critical ?? 0 }}</div>
        <div class="sit-kpi-label">严重待处理</div>
      </div>
      <div class="sit-kpi warn">
        <div class="sit-kpi-num">{{ kpi?.active_preventive ?? 0 }}</div>
        <div class="sit-kpi-label">活跃预防式</div>
      </div>
    </div>

    <!-- 待处理按级别分布 -->
    <div v-if="pendingByLevel.length" class="sit-section">
      <span class="sit-section-title">待处理按级别</span>
      <span
        v-for="l in pendingByLevel"
        :key="l.level"
        class="lvl-chip"
        :class="'lvl-' + (l.level || 'other')"
      >
        {{ l.level }} {{ l.count }}
      </span>
    </div>

    <!-- 近 N 天按级别堆叠趋势 -->
    <div class="sit-section">
      <div class="sit-section-title">
        近 {{ trendDays }} 天告警趋势（按级别堆叠）
        <span class="sit-trend-total">最新一日 {{ lastTotal }}</span>
      </div>
      <svg
        v-if="trendDays > 0"
        class="sit-trend-svg"
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
      >
        <path
          v-for="ly in trendChart.layers"
          :key="ly.level"
          :d="ly.d"
          :fill="ly.color"
          fill-opacity="0.55"
        />
        <circle
          v-if="trendChart.showDot"
          :cx="trendChart.dotCx"
          :cy="trendChart.dotCy"
          r="4"
          :fill="trendChart.dotColor"
        />
      </svg>
      <div v-if="trendDays > 0" class="sit-trend-labels">
        <span v-for="(lb, i) in trendChart.labels" :key="i" :style="labelStyle(i)">{{ lb }}</span>
      </div>
      <el-empty v-else description="暂无告警趋势" :image-size="40" />
    </div>

    <div class="sit-foot">
      <el-button text type="primary" @click="goDetail">查看全部告警 →</el-button>
    </div>
  </el-card>
</template>

<style scoped>
.sit-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.card-title {
  font-weight: 600;
}
.card-sub {
  font-size: 11px;
  color: #c0c4cc;
  white-space: nowrap;
}
.sit-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
.sit-kpi {
  background: #f7f8fa;
  border-radius: 8px;
  padding: 10px 8px;
  text-align: center;
  border-top: 3px solid #409eff;
}
.sit-kpi.danger {
  border-top-color: #f56c6c;
}
.sit-kpi.danger .sit-kpi-num {
  color: #f56c6c;
}
.sit-kpi.warn {
  border-top-color: #e6a23c;
}
.sit-kpi.warn .sit-kpi-num {
  color: #e6a23c;
}
.sit-kpi-num {
  font-size: 26px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}
.sit-kpi-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.sit-section {
  margin-bottom: 10px;
}
.sit-section-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
}
.sit-trend-total {
  font-weight: 600;
  color: #606266;
}
.lvl-chip {
  display: inline-block;
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  margin-right: 6px;
  margin-bottom: 4px;
  color: #fff;
}
.lvl-严重 {
  background: #f56c6c;
}
.lvl-警告 {
  background: #e6a23c;
}
.lvl-提示 {
  background: #409eff;
}
.lvl-other {
  background: #909399;
}
.sit-trend-svg {
  width: 100%;
  height: 160px;
  display: block;
}
.sit-trend-labels {
  position: relative;
  height: 16px;
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}
.sit-foot {
  text-align: right;
  margin-top: 4px;
}
</style>
