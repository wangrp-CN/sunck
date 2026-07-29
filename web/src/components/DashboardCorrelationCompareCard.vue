<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getCorrelationCompare } from "@/api/metrics";
import CorrelationHeatmap from "@/components/CorrelationHeatmap.vue";
import type { CorrelationCompareResp, CorrelationCompareDiffItem } from "@/api/metrics";

// 监控大屏 · 关联热力时间窗对比卡
// 复用已交付的 GET /v1/metrics/correlations/compare：在 A/B 两个时间窗内对原始告警
// 重算跨设备共因聚类并对比，揭示共因热点的时段迁移（本周激增 / 上周有而本周消失）。
// 自带加载、预设切换、60s 自动刷新与卸载清理，不占用大屏 15s 主轮询。

type PresetKey = "week" | "7d" | "30d";

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "7d", label: "近 7 天 vs 前 7 天" },
  { key: "30d", label: "近 30 天 vs 前 30 天" },
  { key: "week", label: "本周 vs 上周" },
];

const preset = ref<PresetKey>("7d");
const onlyCross = ref(true);
const loading = ref(false);
const resp = ref<CorrelationCompareResp | null>(null);
let timer: number | null = null;

// 本地墙钟 → 朴素 ISO（无时区后缀），后端按业务时区 Asia/Shanghai 归一处理
function fmtLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

// 周一 00:00（本地）
function weekStart(d: Date): Date {
  const x = startOfDay(d);
  const dow = (x.getDay() + 6) % 7; // 0=周一 .. 6=周日
  x.setDate(x.getDate() - dow);
  return x;
}

function shift(d: Date, days: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + days);
  return x;
}

function windowOf(key: PresetKey): { a: [Date, Date]; b: [Date, Date] } {
  const now = new Date();
  if (key === "week") {
    const ws = weekStart(now);
    return { a: [ws, now], b: [shift(ws, -7), ws] };
  }
  if (key === "30d") {
    return { a: [shift(now, -30), now], b: [shift(now, -60), shift(now, -30)] };
  }
  // 7d
  return { a: [shift(now, -7), now], b: [shift(now, -14), shift(now, -7)] };
}

async function load() {
  const w = windowOf(preset.value);
  loading.value = true;
  try {
    resp.value = await getCorrelationCompare({
      start_a: fmtLocal(w.a[0]),
      end_a: fmtLocal(w.a[1]),
      start_b: fmtLocal(w.b[0]),
      end_b: fmtLocal(w.b[1]),
      only_cross_device: onlyCross.value,
    });
  } catch (e: any) {
    ElMessage.error(e?.message || "关联热力对比加载失败");
  } finally {
    loading.value = false;
  }
}

const pointsA = computed(() => resp.value?.window_a.points ?? []);
const pointsB = computed(() => resp.value?.window_b.points ?? []);

const changedSorted = computed(() =>
  (resp.value?.diff.changed ?? [])
    .slice()
    .sort((a, b) => Math.abs(b.delta || 0) - Math.abs(a.delta || 0)),
);

const diffTotal = computed(() => {
  if (!resp.value) return 0;
  const d = resp.value.diff;
  return d.new.length + d.removed.length + d.changed.length;
});

function fmtRange(s: string, e: string): string {
  const t = (iso: string) => iso.replace("T", " ").slice(5, 16);
  return `${t(s)} ~ ${t(e)}`;
}

function deltaTag(delta: number): "danger" | "success" | "info" {
  if (delta > 0) return "danger"; // 告警增多 → 风险上升
  if (delta < 0) return "success"; // 告警减少 → 改善
  return "info";
}

function scopeLabel(d: CorrelationCompareDiffItem): string {
  return d.scope_text || d.key || "热点";
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
  <el-card shadow="never" class="bar-card corr-compare-card" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">关联热力时间窗对比</span>
        <div class="compare-tools">
          <el-switch
            v-model="onlyCross"
            size="small"
            inline-prompt
            active-text="仅跨设备"
            inactive-text="全部"
            @change="load"
          />
          <el-select v-model="preset" size="small" style="width: 168px" @change="load">
            <el-option v-for="p in PRESETS" :key="p.key" :label="p.label" :value="p.key" />
          </el-select>
        </div>
      </div>
      <div class="compare-sub" v-if="resp">
        <span class="win-tag win-a">A：{{ fmtRange(resp.window_a.start, resp.window_a.end) }}</span>
        <span class="win-tag win-b">B：{{ fmtRange(resp.window_b.start, resp.window_b.end) }}</span>
        <span class="win-hint">共因热点迁移 · 每 60s 自动刷新</span>
      </div>
    </template>

    <div class="compare-body" v-if="resp">
      <!-- 双窗热力并排 -->
      <div class="heat-grid">
        <div class="heat-pane">
          <div class="pane-head">
            <span class="pane-title win-a">窗口 A</span>
            <span class="pane-stat">
              热力点 {{ resp.window_a.total }} · 跨设备 {{ resp.window_a.cross_device_total }} · 告警 {{ resp.window_a.alarm_total }}
            </span>
          </div>
          <CorrelationHeatmap :points="pointsA" :width="560" :height="300" />
          <div v-if="!pointsA.length" class="pane-empty">该窗口无跨设备共因热力</div>
        </div>
        <div class="heat-pane">
          <div class="pane-head">
            <span class="pane-title win-b">窗口 B</span>
            <span class="pane-stat">
              热力点 {{ resp.window_b.total }} · 跨设备 {{ resp.window_b.cross_device_total }} · 告警 {{ resp.window_b.alarm_total }}
            </span>
          </div>
          <CorrelationHeatmap :points="pointsB" :width="560" :height="300" />
          <div v-if="!pointsB.length" class="pane-empty">该窗口无跨设备共因热力</div>
        </div>
      </div>

      <!-- 变化摘要 -->
      <div class="diff-bar">
        <div class="diff-sum">
          <span class="diff-chip new">新增 {{ resp.diff.new.length }}</span>
          <span class="diff-chip removed">消失 {{ resp.diff.removed.length }}</span>
          <span class="diff-chip changed">变化 {{ resp.diff.changed.length }}</span>
          <span class="diff-total">合计 {{ diffTotal }} 处热点变动</span>
        </div>
        <div class="diff-list" v-if="changedSorted.length">
          <div v-for="d in changedSorted.slice(0, 4)" :key="d.key" class="diff-row">
            <el-tag :type="deltaTag(d.delta)" size="small" effect="dark">
              {{ d.delta > 0 ? "↑" : d.delta < 0 ? "↓" : "→" }}{{ Math.abs(d.delta) }}
            </el-tag>
            <span class="diff-scope">{{ scopeLabel(d) }}</span>
            <span class="diff-meta">
              A {{ d.a_weight }} → B {{ d.b_weight }} · 设备 {{ d.a_device_count ?? 0 }}→{{ d.b_device_count ?? 0 }}
            </span>
          </div>
        </div>
        <div v-else class="diff-empty">两窗共因热点无显著变化</div>
      </div>
    </div>
    <el-empty v-else description="加载中…" :image-size="48" />
  </el-card>
</template>

<style scoped>
.corr-compare-card {
  margin-top: 16px;
}
.compare-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.compare-sub {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #909399;
}
.win-tag {
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.win-a {
  color: #f56c6c;
  background: rgba(245, 108, 108, 0.12);
}
.win-b {
  color: #409eff;
  background: rgba(64, 158, 255, 0.12);
}
.heat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.heat-pane {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fafafa;
}
.pane-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 6px;
}
.pane-title {
  font-weight: 700;
  font-size: 13px;
}
.pane-stat {
  font-size: 12px;
  color: #909399;
}
.pane-empty {
  text-align: center;
  color: #c0c4cc;
  font-size: 12px;
  padding: 12px 0;
}
.diff-bar {
  margin-top: 12px;
  border-top: 1px dashed #ebeef5;
  padding-top: 10px;
}
.diff-sum {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.diff-chip {
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}
.diff-chip.new {
  color: #67c23a;
  background: rgba(103, 194, 58, 0.12);
}
.diff-chip.removed {
  color: #e6a23c;
  background: rgba(230, 162, 60, 0.12);
}
.diff-chip.changed {
  color: #f56c6c;
  background: rgba(245, 108, 108, 0.12);
}
.diff-total {
  color: #909399;
  font-size: 12px;
}
.diff-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.diff-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.diff-scope {
  font-weight: 600;
  color: #303133;
}
.diff-meta {
  color: #909399;
}
.diff-empty {
  margin-top: 8px;
  color: #c0c4cc;
  font-size: 12px;
}
</style>
