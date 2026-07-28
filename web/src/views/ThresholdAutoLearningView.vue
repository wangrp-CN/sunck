<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { MagicStick, Aim, Odometer, Histogram } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import {
  applyThreshold,
  calibrateThreshold,
  getThresholdCalibration,
  type CalibrateResult,
  type ThresholdCalibration,
  type ThresholdSweepPoint,
} from "@/api/intelligence";

const auth = useAuthStore();
const isSuper = computed(() => auth.user?.is_superuser ?? false);

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
const loadingView = ref(false);
const activeThreshold = ref<number>(60);
const latest = ref<ThresholdCalibration | null>(null);

const calibrating = ref(false);
const result = ref<CalibrateResult | null>(null);

// 标定表单参数
const form = ref({
  window_days: 90,
  target_breach_rate: 0.1,
  min_threshold: 40,
  max_threshold: 90,
});

// 手动应用
const applying = ref(false);
const manualThreshold = ref<number>(60);

// ---------------------------------------------------------------------------
// 加载
// ---------------------------------------------------------------------------
async function loadView() {
  loadingView.value = true;
  try {
    const data = await getThresholdCalibration();
    activeThreshold.value = data.active_threshold;
    latest.value = data.latest;
    manualThreshold.value = data.active_threshold;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载阈值配置失败");
  } finally {
    loadingView.value = false;
  }
}

// ---------------------------------------------------------------------------
// 标定
// ---------------------------------------------------------------------------
async function runCalibrate() {
  if (!isSuper.value) {
    ElMessage.warning("仅超级管理员可运行阈值标定");
    return;
  }
  if (form.value.min_threshold >= form.value.max_threshold) {
    ElMessage.warning("推荐阈值下界须小于上界");
    return;
  }
  calibrating.value = true;
  try {
    const r = await calibrateThreshold({ ...form.value });
    result.value = r;
    ElMessage.success(r.message || "标定完成");
  } catch (e: any) {
    ElMessage.error(e?.message || "标定失败");
  } finally {
    calibrating.value = false;
  }
}

// 一键应用标定推荐阈值（来源 auto）
async function applyRecommended() {
  if (!result.value) return;
  if (!isSuper.value) {
    ElMessage.warning("仅超级管理员可应用阈值");
    return;
  }
  applying.value = true;
  try {
    const r = await applyThreshold({
      threshold: result.value.recommended_threshold,
      source: "auto",
      calibration_id: result.value.id ?? result.value.calibration_id,
    });
    activeThreshold.value = r.active_threshold;
    manualThreshold.value = r.active_threshold;
    ElMessage.success(`已应用推荐阈值 ${r.active_threshold}（自学习）`);
    await loadView();
  } catch (e: any) {
    ElMessage.error(e?.message || "应用失败");
  } finally {
    applying.value = false;
  }
}

// 手动设定生效阈值（来源 manual）
async function applyManual() {
  if (!isSuper.value) {
    ElMessage.warning("仅超级管理员可应用阈值");
    return;
  }
  applying.value = true;
  try {
    const r = await applyThreshold({ threshold: manualThreshold.value, source: "manual" });
    activeThreshold.value = r.active_threshold;
    ElMessage.success(`已应用阈值 ${r.active_threshold}（人工设定）`);
    await loadView();
  } catch (e: any) {
    ElMessage.error(e?.message || "应用失败");
  } finally {
    applying.value = false;
  }
}

// ---------------------------------------------------------------------------
// 扫描曲线 SVG（无图表库，内联绘制，与项目趋势图一致）
// ---------------------------------------------------------------------------
const CHART = { w: 680, h: 260, l: 48, r: 16, t: 16, b: 36 };

function buildChart(sweep: ThresholdSweepPoint[]) {
  if (!sweep.length) return null;
  const tMin = sweep[0].threshold;
  const tMax = sweep[sweep.length - 1].threshold;
  const plotW = CHART.w - CHART.l - CHART.r;
  const plotH = CHART.h - CHART.t - CHART.b;
  const xa = (t: number) => CHART.l + ((t - tMin) / Math.max(1, tMax - tMin)) * plotW;
  const ya = (r: number) => CHART.t + (1 - Math.max(0, Math.min(1, r))) * plotH;

  const pts = sweep.map((p) => `${xa(p.threshold).toFixed(1)},${ya(p.breach_rate).toFixed(1)}`);
  const line = pts.join(" ");
  const area = `${CHART.l},${CHART.t + plotH} ${line} ${(CHART.l + plotW).toFixed(1)},${CHART.t + plotH}`;

  const xTicks = [tMin, Math.round((tMin + tMax) / 2), tMax].map((t) => ({ t, x: xa(t) }));
  const yTicks = [0, 0.5, 1].map((r) => ({ r, y: ya(r), label: `${Math.round(r * 100)}%` }));
  return { line, area, xa, ya, xTicks, yTicks };
}

const resultChart = computed(() =>
  result.value ? buildChart(result.value.sweep) : null,
);
const latestChart = computed(() =>
  latest.value && latest.value.sweep.length ? buildChart(latest.value.sweep) : null,
);

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}
function fmtTime(ts: string | null): string {
  if (!ts) return "—";
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts;
}

onMounted(loadView);
</script>

<template>
  <div class="page" v-loading="loadingView">
    <div class="page-head">
      <div class="head-title">
        <el-icon :size="22" class="head-icon"><MagicStick /></el-icon>
        <div>
          <h2>阈值自学习</h2>
          <p class="sub">基于历史风险指数分布自动标定风险预警阈值，实现「学习 → 一键应用 → 自动生效」闭环</p>
        </div>
      </div>
      <el-tag v-if="!isSuper" type="info" effect="plain">只读 · 仅超管可标定/应用</el-tag>
    </div>

    <!-- 当前生效阈值 -->
    <el-card class="card active-card" shadow="never">
      <div class="active-row">
        <div class="active-num">
          <span class="num">{{ activeThreshold }}</span>
          <span class="num-unit">分</span>
        </div>
        <div class="active-meta">
          <div class="meta-line">
            <el-icon><Odometer /></el-icon>
            <span>当前生效的风险预警阈值</span>
          </div>
          <div class="meta-line muted">
            <span>来源：</span>
            <el-tag size="small" :type="latest ? (latest.created_at ? 'success' : 'info') : 'info'" effect="light">
              {{ latest ? "标定应用" : "系统默认" }}
            </el-tag>
            <span v-if="latest" class="muted">· 最近标定 #{{ latest.id }}</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16">
      <!-- 左：运行标定 -->
      <el-col :xs="24" :lg="14">
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-title"><el-icon><Aim /></el-icon><span>运行标定</span></div>
          </template>

          <el-form :model="form" label-width="120px" class="calib-form">
            <el-form-item label="回溯窗口">
              <el-input-number v-model="form.window_days" :min="7" :max="365" :step="1" />
              <span class="suffix">天</span>
              <div class="hint">取近 N 天所有项目风险快照的 risk_index 分布用于标定</div>
            </el-form-item>
            <el-form-item label="目标越阈率">
              <el-slider
                v-model="form.target_breach_rate"
                :min="0.01"
                :max="0.5"
                :step="0.01"
                show-input
                style="width: 320px"
              />
              <div class="hint">期望约 {{ (form.target_breach_rate * 100).toFixed(0) }}% 的历史观测被判为越阈（告警预算）</div>
            </el-form-item>
            <el-form-item label="推荐阈值下界">
              <el-input-number v-model="form.min_threshold" :min="0" :max="100" :step="5" />
              <span class="suffix">分</span>
            </el-form-item>
            <el-form-item label="推荐阈值上界">
              <el-input-number v-model="form.max_threshold" :min="0" :max="100" :step="5" />
              <span class="suffix">分</span>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                :icon="MagicStick"
                :loading="calibrating"
                :disabled="!isSuper"
                @click="runCalibrate"
              >
                运行标定
              </el-button>
              <span v-if="!isSuper" class="muted" style="margin-left: 12px">需超级管理员权限</span>
            </el-form-item>
          </el-form>

          <!-- 标定结果 -->
          <div v-if="result" class="result">
            <el-divider content-position="left">标定结果</el-divider>
            <div class="result-head">
              <div class="rec-num">
                <span class="num">{{ result.recommended_threshold }}</span>
                <span class="num-unit">分</span>
              </div>
              <div class="rec-meta">
                <div>推荐阈值</div>
                <div class="muted">
                  样本 {{ result.sample_count }} 个 · 实际越阈率 {{ fmtPct(result.actual_breach_rate) }}
                </div>
              </div>
              <el-button
                type="success"
                :loading="applying"
                :disabled="!isSuper"
                @click="applyRecommended"
              >
                应用此阈值
              </el-button>
            </div>

            <!-- 扫描曲线 -->
            <div v-if="resultChart" class="chart-wrap">
              <div class="chart-cap">候选阈值 → 实际越阈率扫描曲线（灵敏度可视化）</div>
              <svg :viewBox="`0 0 ${CHART.w} ${CHART.h}`" class="sweep-chart" preserveAspectRatio="xMidYMid meet">
                <line
                  :x1="resultChart.xa(result.recommended_threshold)"
                  :x2="resultChart.xa(result.recommended_threshold)"
                  :y1="CHART.t"
                  :y2="CHART.h - CHART.b"
                  stroke="#f56c6c"
                  stroke-width="1.5"
                  stroke-dasharray="5 4"
                />
                <polygon :points="resultChart.area" fill="rgba(64,158,255,0.12)" />
                <polyline
                  :points="resultChart.line"
                  fill="none"
                  stroke="#409eff"
                  stroke-width="2"
                />
                <circle
                  :cx="resultChart.xa(result.recommended_threshold)"
                  :cy="resultChart.ya(result.actual_breach_rate ?? 0)"
                  r="4.5"
                  fill="#f56c6c"
                />
                <g v-for="(tk, i) in resultChart.xTicks" :key="'x' + i">
                  <line :x1="tk.x" :x2="tk.x" :y1="CHART.h - CHART.b" :y2="CHART.h - CHART.b + 4" stroke="#c0c4cc" />
                  <text :x="tk.x" :y="CHART.h - CHART.b + 18" text-anchor="middle" class="axis-text">{{ tk.t }}</text>
                </g>
                <g v-for="(tk, i) in resultChart.yTicks" :key="'y' + i">
                  <line :x1="CHART.l - 4" :x2="CHART.l" :y1="tk.y" :y2="tk.y" stroke="#c0c4cc" />
                  <text :x="CHART.l - 8" :y="tk.y + 4" text-anchor="end" class="axis-text">{{ tk.label }}</text>
                </g>
              </svg>
              <div class="chart-note">
                虚线/红点：推荐阈值 {{ result.recommended_threshold }} 处对应的实际越阈率
                （{{ fmtPct(result.actual_breach_rate) }}）
              </div>
            </div>

            <!-- 分布统计 -->
            <div v-if="result.stats && Object.keys(result.stats).length" class="stats-grid">
              <div class="stat"><span>最小</span><b>{{ result.stats.min }}</b></div>
              <div class="stat"><span>最大</span><b>{{ result.stats.max }}</b></div>
              <div class="stat"><span>均值</span><b>{{ result.stats.mean }}</b></div>
              <div class="stat"><span>中位数</span><b>{{ result.stats.median }}</b></div>
              <div class="stat"><span>P75</span><b>{{ result.stats.p75 }}</b></div>
              <div class="stat"><span>P90</span><b>{{ result.stats.p90 }}</b></div>
              <div class="stat"><span>P95</span><b>{{ result.stats.p95 }}</b></div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右：标定历史 + 手动设定 -->
      <el-col :xs="24" :lg="10">
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-title"><el-icon><Histogram /></el-icon><span>最近一次标定</span></div>
          </template>
          <div v-if="latest" class="latest">
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item label="标定 ID">#{{ latest.id }}</el-descriptions-item>
              <el-descriptions-item label="时间">{{ fmtTime(latest.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="采样窗口">{{ latest.window_days }} 天</el-descriptions-item>
              <el-descriptions-item label="样本数">{{ latest.sample_count }}</el-descriptions-item>
              <el-descriptions-item label="目标越阈率">{{ fmtPct(latest.target_breach_rate) }}</el-descriptions-item>
              <el-descriptions-item label="实际越阈率">{{ fmtPct(latest.actual_breach_rate) }}</el-descriptions-item>
              <el-descriptions-item label="标定前阈值">{{ latest.current_threshold }}</el-descriptions-item>
              <el-descriptions-item label="推荐阈值">
                <b style="color: #f56c6c">{{ latest.recommended_threshold }}</b>
              </el-descriptions-item>
            </el-descriptions>

            <div v-if="latestChart" class="chart-wrap">
              <svg :viewBox="`0 0 ${CHART.w} ${CHART.h}`" class="sweep-chart" preserveAspectRatio="xMidYMid meet">
                <polygon :points="latestChart.area" fill="rgba(64,158,255,0.10)" />
                <polyline :points="latestChart.line" fill="none" stroke="#409eff" stroke-width="2" />
                <line
                  :x1="latestChart.xa(latest!.recommended_threshold)"
                  :x2="latestChart.xa(latest!.recommended_threshold)"
                  :y1="CHART.t"
                  :y2="CHART.h - CHART.b"
                  stroke="#f56c6c"
                  stroke-width="1.5"
                  stroke-dasharray="5 4"
                />
                <g v-for="(tk, i) in latestChart.xTicks" :key="'x' + i">
                  <line :x1="tk.x" :x2="tk.x" :y1="CHART.h - CHART.b" :y2="CHART.h - CHART.b + 4" stroke="#c0c4cc" />
                  <text :x="tk.x" :y="CHART.h - CHART.b + 18" text-anchor="middle" class="axis-text">{{ tk.t }}</text>
                </g>
                <g v-for="(tk, i) in latestChart.yTicks" :key="'y' + i">
                  <line :x1="CHART.l - 4" :x2="CHART.l" :y1="tk.y" :y2="tk.y" stroke="#c0c4cc" />
                  <text :x="CHART.l - 8" :y="tk.y + 4" text-anchor="end" class="axis-text">{{ tk.label }}</text>
                </g>
              </svg>
            </div>
            <el-empty v-else description="该记录无扫描曲线" :image-size="60" />
          </div>
          <el-empty v-else description="暂无标定记录，运行一次标定以初始化" />
        </el-card>

        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-title"><el-icon><Odometer /></el-icon><span>手动设定生效阈值</span></div>
          </template>
          <el-form label-width="110px">
            <el-form-item label="生效阈值">
              <el-input-number v-model="manualThreshold" :min="0" :max="100" :step="1" />
              <span class="suffix">分</span>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                :loading="applying"
                :disabled="!isSuper"
                @click="applyManual"
              >
                立即应用（人工）
              </el-button>
              <span v-if="!isSuper" class="muted" style="margin-left: 12px">需超级管理员权限</span>
            </el-form-item>
          </el-form>
          <div class="muted tip">适用于临时人工干预；经「运行标定 → 应用」得到的阈值会被标记为「标定应用」，可在历史中追溯。</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page {
  padding: 4px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-icon {
  color: #409eff;
}
.head-title h2 {
  margin: 0;
  font-size: 18px;
}
.sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: #909399;
}
.card {
  margin-bottom: 16px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.active-card {
  background: linear-gradient(135deg, #ecf5ff 0%, #f4f9ff 100%);
}
.active-row {
  display: flex;
  align-items: center;
  gap: 24px;
}
.active-num .num,
.rec-num .num {
  font-size: 40px;
  font-weight: 700;
  color: #f56c6c;
  line-height: 1;
}
.num-unit {
  font-size: 14px;
  color: #909399;
  margin-left: 4px;
}
.active-meta .meta-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.muted {
  color: #909399;
  font-size: 12px;
}
.hint {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
.suffix {
  margin-left: 6px;
  color: #606266;
}
.calib-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
}
.result-head {
  display: flex;
  align-items: center;
  gap: 20px;
}
.rec-num .num {
  color: #f56c6c;
  font-size: 32px;
}
.rec-meta {
  flex: 1;
}
.result {
  margin-top: 8px;
}
.chart-wrap {
  margin-top: 12px;
}
.chart-cap {
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}
.sweep-chart {
  width: 100%;
  height: auto;
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.axis-text {
  font-size: 10px;
  fill: #909399;
}
.chart-note {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
  margin-top: 12px;
}
.stat {
  background: #f7f8fa;
  border-radius: 6px;
  padding: 8px 4px;
  text-align: center;
}
.stat span {
  display: block;
  font-size: 11px;
  color: #909399;
}
.stat b {
  font-size: 15px;
  color: #303133;
}
.tip {
  margin-top: 4px;
}
@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>
