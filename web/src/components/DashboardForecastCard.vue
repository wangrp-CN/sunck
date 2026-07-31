<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { listForecastMetrics, listForecasts, previewForecast } from "@/api/forecast";
import type { ForecastItem, ForecastMetric, ForecastPreview } from "@/api/forecast";
import ForecastChart from "@/components/ForecastChart.vue";

// 监控大屏 · 风险预测卡（Phase 5 M4 + 可解释化）
// 左侧：预测 TOP 列表（指标由 GET /metrics 动态驱动）；右侧：选中对象的历史序列 +
// 预测点 + 95% 置信带图 + 特征贡献归因（可解释化）+ 模板解读（GET /v1/forecasts/preview）。
// 60s 自动刷新，不占大屏主轮询。

// 指标元数据的本地兜底（与后端 METRIC_REGISTRY 一致；GET /metrics 加载后覆盖标签/阈值）
interface MetricMetaLocal {
  scope_type: "project" | "device";
  direction: string;
  threshold: number;
  label: string;
  short: string;
  description: string;
}
const METRIC_FALLBACK: Record<string, MetricMetaLocal> = {
  risk_index: { scope_type: "project", direction: "low_good", threshold: 60, label: "项目风险指数", short: "风险", description: "项目综合风险指数(0-100)，越低越好" },
  health_score: { scope_type: "device", direction: "high_good", threshold: 60, label: "设备健康分", short: "健康", description: "设备健康分(0-100)，越高越好" },
};
const SHORT_FALLBACK: Record<string, string> = { risk_index: "风险", health_score: "健康" };

const metrics = ref<ForecastMetric[]>([]);
const metricMap = computed(() => new Map(metrics.value.map((m) => [m.key, m])));
function metaOf(m: string): MetricMetaLocal {
  const d = metricMap.value.get(m);
  const fb = METRIC_FALLBACK[m];
  return {
    scope_type: d?.scope_type ?? fb?.scope_type ?? "project",
    direction: d?.direction ?? fb?.direction ?? "low_good",
    threshold: d?.preventive_threshold ?? fb?.threshold ?? 60,
    label: d?.label ?? fb?.label ?? m,
    short: SHORT_FALLBACK[m] ?? (d?.label ?? m).slice(0, 2),
    description: d?.description ?? fb?.description ?? "",
  };
}
// 指标清单未加载时回退到兜底两项，保证 radio 始终可渲染
const metricOptions = computed<{ key: string; label: string }[]>(() =>
  metrics.value.length
    ? metrics.value.map((m) => ({ key: m.key, label: m.label }))
    : Object.entries(METRIC_FALLBACK).map(([key, v]) => ({ key, label: v.label })),
);

const metric = ref<string>("risk_index");
const loading = ref(false);
const items = ref<ForecastItem[]>([]);
const selectedKey = ref<string | null>(null); // `${scope_type}:${ref_id}`
const preview = ref<ForecastPreview | null>(null);
const previewLoading = ref(false);
let timer: number | null = null;

function scopeOf(m: string) {
  return metaOf(m).scope_type as "project" | "device";
}

// 高/中/低（risk）与 优/良/中/差（health）→ tag type
function levelTag(level: string | null): "danger" | "warning" | "success" | "info" {
  if (level === "高" || level === "差") return "danger";
  if (level === "中") return "warning";
  if (level === "低" || level === "优" || level === "良") return "success";
  return "info";
}

const topItems = computed(() => {
  const arr = [...items.value];
  // low_good（risk）：预测值降序（高=差在前）；high_good（health）：升序（低=差在前）
  if (metaOf(metric.value).direction === "high_good") arr.sort((a, b) => a.forecast_value - b.forecast_value);
  return arr.slice(0, 5);
});

const selected = computed(
  () => topItems.value.find((i) => `${i.scope_type}:${i.ref_id}` === selectedKey.value) ?? null,
);

// 预测值相对当前值的趋势箭头
function trendArrow(it: ForecastItem): string {
  if (it.forecast_value > it.last_value) return "↑";
  if (it.forecast_value < it.last_value) return "↓";
  return "→";
}
function trendClass(it: ForecastItem): string {
  const up = it.forecast_value > it.last_value;
  // low_good 上升 = 恶化；high_good 下降 = 恶化
  const worse = metaOf(it.metric).direction === "low_good" ? up : !up && it.forecast_value !== it.last_value;
  return worse ? "worse" : "better";
}

async function loadMetrics() {
  try {
    metrics.value = await listForecastMetrics();
  } catch {
    // 保留兜底清单
  }
}

async function load() {
  loading.value = true;
  try {
    const resp = await listForecasts({ scope_type: scopeOf(metric.value), metric: metric.value });
    items.value = resp.items;
    // 默认选中最差对象；已有选择且仍在列表中则保持
    const keys = topItems.value.map((i) => `${i.scope_type}:${i.ref_id}`);
    if (!selectedKey.value || !keys.includes(selectedKey.value)) {
      selectedKey.value = keys[0] ?? null;
    }
  } catch (e: any) {
    ElMessage.error(e?.message || "预测列表加载失败");
  } finally {
    loading.value = false;
  }
}

async function loadPreview() {
  const it = selected.value;
  if (!it) {
    preview.value = null;
    return;
  }
  previewLoading.value = true;
  try {
    preview.value = await previewForecast({
      ref_id: it.ref_id,
      scope_type: it.scope_type,
      metric: it.metric,
    });
  } catch (e: any) {
    preview.value = null;
    ElMessage.error(e?.message || "预测预览加载失败");
  } finally {
    previewLoading.value = false;
  }
}

function selectItem(it: ForecastItem) {
  selectedKey.value = `${it.scope_type}:${it.ref_id}`;
}

// 值变即重拉：watch 比模板 @change 更稳健（程序化赋值同样触发）
watch(metric, () => {
  selectedKey.value = null;
  preview.value = null;
  void load();
});
watch(selectedKey, () => void loadPreview());

onMounted(() => {
  void loadMetrics();
  void load();
  timer = window.setInterval(() => void load(), 60000);
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
  timer = null;
});
</script>

<template>
  <el-card shadow="never" class="bar-card forecast-card" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">智能预测 · 趋势外推</span>
        <div class="fc-tools">
          <el-radio-group v-model="metric" size="small">
            <el-radio-button v-for="opt in metricOptions" :key="opt.key" :value="opt.key">{{ opt.label }}</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div class="fc-sub">
        {{ metaOf(metric).description }} · 每 60s 刷新
      </div>
    </template>

    <div v-if="topItems.length" class="fc-body">
      <!-- 左：TOP 列表 -->
      <div class="fc-list">
        <div
          v-for="it in topItems"
          :key="it.id"
          class="fc-row"
          :class="{ active: `${it.scope_type}:${it.ref_id}` === selectedKey }"
          @click="selectItem(it)"
        >
          <span class="fc-name" :title="it.name || it.ref_id">{{ it.name || it.ref_id }}</span>
          <span class="fc-vals">
            {{ it.last_value.toFixed(0) }}
            <i class="fc-arrow" :class="trendClass(it)">{{ trendArrow(it) }}</i>
            {{ it.forecast_value.toFixed(0) }}
          </span>
          <el-tag :type="levelTag(it.forecast_level)" size="small" effect="dark">
            {{ it.forecast_level || "—" }}
          </el-tag>
        </div>
      </div>

      <!-- 右：预测图 -->
      <div class="fc-chart" v-loading="previewLoading">
        <template v-if="preview">
          <div class="fc-chart-head" v-if="selected">
            <span class="fc-chart-title">{{ selected.name || selected.ref_id }}</span>
            <span class="fc-chart-meta" v-if="preview.forecast">
              {{ preview.forecast.horizon_days }} 天后{{ metaOf(metric).short }}
              {{ preview.forecast.forecast_value.toFixed(0) }}
              （95% CI {{ preview.forecast.forecast_lower.toFixed(0) }}~{{ preview.forecast.forecast_upper.toFixed(0) }}）
            </span>
          </div>
          <ForecastChart
            :series="preview.series"
            :forecast="preview.forecast"
            :threshold="metaOf(metric).threshold"
            :width="430"
            :height="150"
            :color="metaOf(metric).direction === 'low_good' ? '#f56c6c' : '#67c23a'"
            :contributions="preview.forecast?.contributions ?? undefined"
          />
          <div v-if="preview.forecast?.explanation" class="fc-explain">
            <span class="fc-explain-label">解读</span>{{ preview.forecast.explanation }}
          </div>
          <div v-if="!preview.forecast" class="fc-accum">数据积累中：快照样本不足 3 天，暂无法外推预测</div>
        </template>
        <el-empty v-else description="选择左侧对象查看预测" :image-size="42" />
      </div>
    </div>
    <el-empty v-else-if="!loading" description="暂无预测数据（日快照积累≥3天后自动生成）" :image-size="48" />
  </el-card>
</template>

<style scoped>
.forecast-card {
  margin-top: 16px;
}
.fc-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fc-sub {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
.fc-body {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(0, 470px);
  gap: 16px;
  align-items: start;
}
.fc-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  font-size: 13px;
}
.fc-row:hover {
  background: #f5f7fa;
}
.fc-row.active {
  background: rgba(64, 158, 255, 0.08);
  border-color: rgba(64, 158, 255, 0.35);
}
.fc-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: #303133;
}
.fc-vals {
  font-variant-numeric: tabular-nums;
  color: #606266;
  white-space: nowrap;
}
.fc-arrow {
  font-style: normal;
  font-weight: 700;
  margin: 0 2px;
}
.fc-arrow.worse {
  color: #f56c6c;
}
.fc-arrow.better {
  color: #67c23a;
}
.fc-chart-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.fc-chart-title {
  font-weight: 700;
  font-size: 13px;
  color: #303133;
}
.fc-chart-meta {
  font-size: 12px;
  color: #e6a23c;
  font-weight: 600;
}
.fc-accum {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
.fc-explain {
  margin-top: 8px;
  padding: 7px 10px;
  background: #f4f4f5;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #606266;
}
.fc-explain-label {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  border-radius: 3px;
  background: #ecf5ff;
  color: #409eff;
  font-weight: 600;
}
@media (max-width: 960px) {
  .fc-body {
    grid-template-columns: 1fr;
  }
}
</style>
