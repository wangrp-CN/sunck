<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { getDispositionStats, type DispositionStats } from "@/api/disposition";
import { fetchProjects } from "@/api/project";

const loading = ref(false);
const data = ref<DispositionStats | null>(null);
const projectNames = ref<Map<number, string>>(new Map());
let timer: ReturnType<typeof setInterval> | null = null;

function fmtRate(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return (v * 100).toFixed(0) + "%";
}
function fmtHours(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1) + " h";
}

const OUTCOME_ORDER = ["已解决", "部分解决", "未解决", "误报", "未填写"];
const OUTCOME_COLORS: Record<string, string> = {
  已解决: "#67c23a",
  部分解决: "#409eff",
  未解决: "#e6a23c",
  误报: "#f56c6c",
  未填写: "#c0c4cc",
};
function outcomeColor(key: string): string {
  return OUTCOME_COLORS[key] || "#909399";
}

// 按处置结果分布：固定顺序优先，其余（未知 key）追加在后
const outcomeRows = computed(() => {
  if (!data.value) return [];
  const map = data.value.by_outcome || {};
  const keys = [
    ...OUTCOME_ORDER.filter((k) => k in map),
    ...Object.keys(map).filter((k) => !OUTCOME_ORDER.includes(k)),
  ];
  const total = keys.reduce((s, k) => s + (map[k] || 0), 0) || 1;
  return keys.map((k) => ({
    key: k,
    count: map[k] || 0,
    pct: ((map[k] || 0) / total) * 100,
    color: outcomeColor(k),
  }));
});

// 按项目闭环率：按处置总数降序取前 6，映射项目名
const projectRows = computed(() => {
  if (!data.value) return [];
  const rows = [...(data.value.by_project || [])]
    .filter((p) => p.project_id && p.project_id !== 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, 6);
  return rows.map((p) => ({
    project_id: p.project_id,
    name: projectNames.value.get(p.project_id) || `项目 ${p.project_id}`,
    closure_rate: p.closure_rate,
    total: p.total,
    resolved: p.resolved,
  }));
});

const pendingCount = computed(() => {
  if (!data.value) return 0;
  return Math.max(0, data.value.total - data.value.resolved);
});

async function load() {
  loading.value = true;
  try {
    data.value = await getDispositionStats({ days: 30 });
  } catch {
    data.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadProjects() {
  try {
    const page = await fetchProjects({ size: 200 });
    const m = new Map<number, string>();
    for (const p of page.items || []) m.set(p.id, p.name);
    projectNames.value = m;
  } catch {
    /* 名称映射失败不影响主数据 */
  }
}

onMounted(() => {
  load();
  void loadProjects();
  timer = setInterval(load, 60000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <el-card class="disp-card" shadow="hover" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span class="card-title">处置效果闭环</span>
        <span class="card-sub">处置闭环率与时效 · 近 30 天</span>
      </div>
    </template>

    <div class="metric-row">
      <div class="metric">
        <div
          class="metric-val"
          :class="data && data.closure_rate !== null && data.closure_rate >= 0.8 ? 'good' : 'warn'"
        >
          {{ fmtRate(data?.closure_rate ?? null) }}
        </div>
        <div class="metric-label">闭环率</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ data?.total ?? "—" }}</div>
        <div class="metric-label">处置总数</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ data?.resolved ?? "—" }}</div>
        <div class="metric-label">已解决</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ fmtHours(data?.avg_duration_hours ?? null) }}</div>
        <div class="metric-label">平均处置时长</div>
      </div>
      <div class="metric">
        <div class="metric-val">{{ pendingCount }}</div>
        <div class="metric-label">待改进</div>
      </div>
    </div>

    <el-divider>按处置结果</el-divider>
    <div v-if="data" class="by-outcome">
      <div v-for="o in outcomeRows" :key="o.key" class="oc-row">
        <span class="oc-name">{{ o.key }}</span>
        <div class="oc-track">
          <div class="oc-fill" :style="{ width: o.pct + '%', background: o.color }" />
        </div>
        <span class="oc-count">{{ o.count }}</span>
      </div>
    </div>

    <el-divider>按项目闭环率（Top 6）</el-divider>
    <div v-if="data" class="by-project">
      <div v-for="p in projectRows" :key="p.project_id" class="bp-row">
        <span class="bp-name" :title="p.name">{{ p.name }}</span>
        <span class="bp-rate">{{ fmtRate(p.closure_rate) }}</span>
        <span class="bp-count">{{ p.resolved }}/{{ p.total }}</span>
      </div>
      <div v-if="projectRows.length === 0" class="bp-empty">暂无按项目统计</div>
    </div>

    <el-empty v-if="!data" :image-size="50" description="暂无处置数据" />
  </el-card>
</template>

<style scoped>
.disp-card { height: 100%; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; }
.card-title { font-weight: 600; font-size: 15px; }
.card-sub { color: #909399; font-size: 12px; }
.metric-row { display: flex; justify-content: space-between; gap: 8px; }
.metric { text-align: center; flex: 1; }
.metric-val { font-size: 22px; font-weight: 700; color: #303133; }
.metric-val.good { color: #67c23a; }
.metric-val.warn { color: #e6a23c; }
.metric-label { font-size: 12px; color: #909399; margin-top: 2px; }

.by-outcome { display: flex; flex-direction: column; gap: 6px; }
.oc-row { display: flex; align-items: center; gap: 8px; }
.oc-name { width: 56px; font-size: 13px; color: #606266; white-space: nowrap; }
.oc-track { flex: 1; height: 12px; background: #f0f2f5; border-radius: 6px; overflow: hidden; }
.oc-fill { height: 100%; border-radius: 6px; transition: width 0.4s ease; }
.oc-count { width: 30px; text-align: right; font-size: 13px; color: #303133; }

.by-project { display: flex; flex-direction: column; gap: 6px; }
.bp-row { display: flex; align-items: center; justify-content: space-between; font-size: 13px; }
.bp-name {
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 150px;
}
.bp-rate { font-weight: 600; color: #303133; }
.bp-count { color: #909399; font-size: 12px; }
.bp-empty { color: #909399; font-size: 12px; }
</style>
