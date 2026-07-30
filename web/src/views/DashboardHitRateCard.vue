<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { getForecastHitRate, type PredictionHitRate } from "@/api/forecast";

const loading = ref(false);
const data = ref<PredictionHitRate | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

function fmtRate(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return (v * 100).toFixed(0) + "%";
}
function fmtHours(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1) + " h";
}

async function load() {
  loading.value = true;
  try {
    data.value = await getForecastHitRate({ days: 30 });
  } catch {
    data.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  load();
  timer = setInterval(load, 60000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <el-card class="hitrate-card" shadow="hover" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">预测命中率</span>
        <span class="card-sub">预测性预警闭环验证 · 近 30 天</span>
      </div>
    </template>

    <div class="metric-row">
      <div class="metric">
        <div class="metric-val" :class="data && data.hit_rate !== null && data.hit_rate >= 0.6 ? 'good' : 'warn'">
          {{ fmtRate(data?.hit_rate ?? null) }}
        </div>
        <div class="metric-label">命中率</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ data?.verifiable ?? "—" }}</div>
        <div class="metric-label">已验证预测</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ data?.hits ?? "—" }}</div>
        <div class="metric-label">命中</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ data?.false_positives ?? "—" }}</div>
        <div class="metric-label">误报</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ fmtHours(data?.avg_lead_hours ?? null) }}</div>
        <div class="metric-label">平均提前量</div>
      </div>
    </div>

    <el-divider>按指标</el-divider>
    <div v-if="data" class="by-metric">
      <div v-for="(m, key) in data.by_metric" :key="key" class="bm-row">
        <span class="bm-name">{{ key === 'risk_index' ? '项目风险' : key === 'health_score' ? '设备健康' : key }}</span>
        <span class="bm-rate">{{ fmtRate(m.hit_rate) }}</span>
        <span class="bm-count">{{ m.hits }}/{{ m.verifiable }} 命中</span>
      </div>
      <div v-if="data.pending > 0" class="bm-pending">另有 {{ data.pending }} 条预测窗口未结束，待验证</div>
    </div>
    <el-empty v-else :image-size="50" description="暂无预测数据" />
  </el-card>
</template>

<style scoped>
.hitrate-card { height: 100%; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; }
.card-title { font-weight: 600; font-size: 15px; }
.card-sub { color: #909399; font-size: 12px; }
.metric-row { display: flex; justify-content: space-between; gap: 8px; }
.metric { text-align: center; flex: 1; }
.metric-val { font-size: 22px; font-weight: 700; color: #303133; }
.metric-val.good { color: #67c23a; }
.metric-val.warn { color: #e6a23c; }
.metric-label { font-size: 12px; color: #909399; margin-top: 2px; }
.by-metric { display: flex; flex-direction: column; gap: 6px; }
.bm-row { display: flex; align-items: center; justify-content: space-between; font-size: 13px; }
.bm-name { color: #606266; }
.bm-rate { font-weight: 600; color: #303133; }
.bm-count { color: #909399; font-size: 12px; }
.bm-pending { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
