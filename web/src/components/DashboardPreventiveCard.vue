<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getPreventiveSummary, type PreventiveSummary } from "@/api/alarm";

// 监控大屏 · 活跃预防式告警卡
// 展示预测引擎（置信带越阈）生成的预防式预警中，仍处于「待处理」的活跃量，
// 按监测指标 / 告警级别分布，并列出最近明细，点击直达告警页对应筛选。
// 60s 自动刷新，不占大屏主轮询（独立定时器）。

const router = useRouter();
const loading = ref(false);
const data = ref<PreventiveSummary | null>(null);
let timer: number | null = null;

const METRIC_LABELS: Record<string, string> = {
  risk_index: "项目风险指数",
  health_score: "设备健康分",
};

const metricEntries = computed(() =>
  Object.entries(data.value?.by_metric ?? {}).map(([k, v]) => ({
    key: k,
    label: METRIC_LABELS[k] ?? k,
    count: v,
  })),
);
const levelEntries = computed(() =>
  Object.entries(data.value?.by_level ?? {}).map(([k, v]) => ({ level: k, count: v })),
);
const maxMetric = computed(() => Math.max(1, ...metricEntries.value.map((m) => m.count)));
const total = computed(() => data.value?.total ?? 0);

function fmtTime(t: string | null): string {
  if (!t) return "—";
  return t.replace("T", " ").slice(0, 16);
}

async function load() {
  loading.value = true;
  try {
    data.value = await getPreventiveSummary();
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false;
  }
}

function goDetail() {
  router.push("/alarms?alarm_type=preventive_alert");
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
  <el-card shadow="never" class="prev-card" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">活跃预防式告警</span>
        <span class="card-sub">预测置信带越阈提前预警 · 60s 刷新</span>
      </div>
    </template>

    <div class="prev-bignum" :class="{ zero: total === 0 }">
      {{ total === 0 ? 0 : total }}
      <span class="prev-bignum-label">条待处置</span>
    </div>

    <div v-if="metricEntries.length" class="prev-section">
      <div class="prev-section-title">按监测指标</div>
      <div v-for="m in metricEntries" :key="m.key" class="bar-row">
        <span class="bar-label">{{ m.label }}</span>
        <div class="bar-track">
          <div
            class="bar-fill"
            :style="{ width: (m.count / maxMetric) * 100 + '%', background: '#e6a23c' }"
          />
        </div>
        <span class="bar-val">{{ m.count }}</span>
      </div>
    </div>

    <div v-if="levelEntries.length" class="prev-section">
      <div class="prev-section-title">按告警级别</div>
      <span
        v-for="l in levelEntries"
        :key="l.level"
        class="lvl-chip"
        :class="'lvl-' + (l.level || 'other')"
      >
        {{ l.level }} {{ l.count }}
      </span>
    </div>

    <div v-if="(data?.recent?.length ?? 0) > 0" class="prev-recent">
      <div v-for="r in data!.recent" :key="r.id" class="prev-recent-item">
        <el-tag size="small" :type="r.alarm_level === '严重' ? 'danger' : 'warning'" effect="dark">
          {{ r.alarm_level || "警告" }}
        </el-tag>
        <span class="prev-recent-info">{{ r.alarm_info }}</span>
        <span class="prev-recent-time">{{ fmtTime(r.alarm_time) }}</span>
      </div>
    </div>
    <el-empty v-else-if="!loading" description="暂无活跃预防式告警" :image-size="40" />

    <div class="prev-foot">
      <el-button text type="primary" @click="goDetail">查看全部明细 →</el-button>
    </div>
  </el-card>
</template>

<style scoped>
.prev-card {
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
.prev-bignum {
  font-size: 30px;
  font-weight: 700;
  color: #f56c6c;
  line-height: 1.2;
  margin-bottom: 12px;
}
.prev-bignum.zero {
  color: #67c23a;
}
.prev-bignum-label {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 6px;
}
.prev-section {
  margin-bottom: 10px;
}
.prev-section-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.bar-label {
  width: 92px;
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
.prev-recent {
  max-height: 170px;
  overflow-y: auto;
  margin-bottom: 8px;
}
.prev-recent-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  border-bottom: 1px dashed #f0f0f0;
}
.prev-recent-info {
  flex: 1;
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.prev-recent-time {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.prev-foot {
  text-align: right;
  margin-top: 4px;
}
</style>
