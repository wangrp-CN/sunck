<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getForecastABHitRate,
  getForecastDefaultModel,
  runForecastBacktest,
  setForecastDefaultModel,
  type ABHitRate,
  type ABModelRow,
  type ForecastDefaultModel,
} from "@/api/forecast";

const loading = ref(false);
const backtesting = ref(false);
const switching = ref(false);
const data = ref<ABHitRate | null>(null);
const defaultModel = ref<ForecastDefaultModel | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

// 当前线上默认模型是否为 hw_v1
const onlineIsHw = computed(() => defaultModel.value?.model_version === "hw_v1");
// 当 hw_v1 表现更优且尚未上线时，提示一键切换
const showSwitchSuggestion = computed(
  () =>
    !!data.value?.comparison?.better &&
    data.value.comparison.challenger === "hw_v1" &&
    !onlineIsHw.value,
);

function fmtRate(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return (v * 100).toFixed(0) + "%";
}
function fmtPP(v: number | null): string {
  if (v === null || v === undefined) return "—";
  const pp = v * 100;
  return (pp >= 0 ? "+" : "") + pp.toFixed(0) + "pp";
}
function fmtHours(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1) + " h";
}

async function load() {
  loading.value = true;
  try {
    data.value = await getForecastABHitRate({ days: 90 });
  } catch {
    data.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadDefault() {
  try {
    defaultModel.value = await getForecastDefaultModel();
  } catch {
    defaultModel.value = null;
  }
}

async function switchToHw() {
  switching.value = true;
  try {
    await setForecastDefaultModel("hw_v1");
    ElMessage.success("已切换上线模型为 Holt-Winters(hw_v1)，预测与预警已即时重算");
    await Promise.all([loadDefault(), load()]);
  } catch {
    ElMessage.error("切换失败");
  } finally {
    switching.value = false;
  }
}

async function runBacktest() {
  backtesting.value = true;
  try {
    await runForecastBacktest({ days: 90, horizon_days: 7 });
    ElMessage.success("回测已完成，已刷新对比");
    await load();
  } catch {
    ElMessage.error("回测失败");
  } finally {
    backtesting.value = false;
  }
}

const hasData = () =>
  !!data.value && data.value.models.some((m: ABModelRow) => m.verifiable > 0);

onMounted(() => {
  load();
  loadDefault();
  timer = setInterval(load, 60000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <el-card class="ab-card" shadow="hover" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">
          预测模型 A/B 对比
          <span v-if="defaultModel" class="online-tag"
            >· 线上：{{ defaultModel?.available.find((a) => a.model_version === defaultModel?.model_version)?.label || defaultModel?.model_version }}</span
          >
        </span>
        <el-button
          size="small"
          type="primary"
          :loading="backtesting"
          @click="runBacktest"
          >重新回测</el-button
        >
      </div>
    </template>

    <template v-if="hasData()">
      <!-- 增量对比横幅 -->
      <div
        v-if="data!.comparison"
        class="cmp-banner"
        :class="data!.comparison!.better ? 'good' : 'warn'"
      >
        <el-icon v-if="data!.comparison!.better"><CircleCheck /></el-icon>
        <el-icon v-else><WarningFilled /></el-icon>
        <span>{{ data!.comparison!.summary }}</span>
      </div>

      <!-- 一键切换建议（hw_v1 更优且尚未上线） -->
      <div v-if="showSwitchSuggestion" class="switch-banner">
        <el-icon><MagicStick /></el-icon>
        <span>hw_v1 表现更优，建议切换为上线默认模型</span>
        <el-button size="small" type="success" :loading="switching" @click="switchToHw"
          >一键切换</el-button
        >
      </div>

      <!-- 各模型并列 -->
      <div class="model-row">
        <div v-for="m in data!.models" :key="m.model_version" class="model-col">
          <div class="model-name">{{ m.label }}</div>
          <div class="model-ver">{{ m.model_version }}</div>
          <div class="metric-line">
            <span class="ml-label">命中率</span>
            <span class="ml-val" :class="m.hit_rate !== null && m.hit_rate >= 0.6 ? 'good' : 'warn'">{{
              fmtRate(m.hit_rate)
            }}</span>
          </div>
          <div class="metric-line">
            <span class="ml-label">误报率</span>
            <span class="ml-val">{{ fmtRate(m.false_positive_rate) }}</span>
          </div>
          <div class="metric-line">
            <span class="ml-label">平均提前量</span>
            <span class="ml-val">{{ fmtHours(m.avg_lead_hours) }}</span>
          </div>
          <div class="model-foot">已验证 {{ m.verifiable }} · 命中 {{ m.hits }}</div>
        </div>
      </div>

      <!-- 增量明细 -->
      <div v-if="data!.comparison" class="delta-row">
        <el-tag size="small" :type="data!.comparison!.hit_rate_delta! >= 0 ? 'success' : 'danger'">
          命中率 {{ fmtPP(data!.comparison!.hit_rate_delta) }}
        </el-tag>
        <el-tag
          size="small"
          :type="(data!.comparison!.false_positive_rate_delta ?? 0) <= 0 ? 'success' : 'danger'"
        >
          误报率 {{ fmtPP(data!.comparison!.false_positive_rate_delta) }}
        </el-tag>
        <el-tag size="small" type="info">提前量 {{ fmtHours(data!.comparison!.lead_delta_hours) }}</el-tag>
      </div>
    </template>

    <el-empty v-else :image-size="60" description="暂无回测数据，点击「重新回测」生成 A/B 对比" />
  </el-card>
</template>

<style scoped>
.ab-card {
  height: 100%;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-weight: 600;
  font-size: 15px;
}
.online-tag {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
  margin-left: 6px;
}
.switch-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 6px;
  margin-bottom: 12px;
  background: #ecf5ff;
  color: #409eff;
}
.switch-banner .el-button {
  margin-left: auto;
}
.cmp-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 6px;
  margin-bottom: 12px;
}
.cmp-banner.good {
  background: #f0f9eb;
  color: #67c23a;
}
.cmp-banner.warn {
  background: #fdf6ec;
  color: #e6a23c;
}
.model-row {
  display: flex;
  gap: 12px;
}
.model-col {
  flex: 1;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafafa;
}
.model-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.model-ver {
  font-size: 11px;
  color: #c0c4cc;
  margin-bottom: 6px;
}
.metric-line {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin: 3px 0;
}
.ml-label {
  color: #909399;
}
.ml-val {
  font-weight: 600;
  color: #303133;
}
.ml-val.good {
  color: #67c23a;
}
.ml-val.warn {
  color: #e6a23c;
}
.model-foot {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
.delta-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
</style>
