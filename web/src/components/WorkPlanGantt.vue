<script setup lang="ts">
import { computed } from "vue";
import type { WorkPlan, WorkPlanStatus } from "@/types";

const props = defineProps<{
  plans: WorkPlan[];
}>();
const emit = defineEmits<{ (e: "select", plan: WorkPlan): void }>();

// 解析 ISO 日期（YYYY-MM-DD 或 YYYY-MM-DDTHH:mm:ss），按本地时间，不受时区漂移影响
function parseISO(s: string | null | undefined): number | null {
  if (!s) return null;
  const m = s.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/,
  );
  if (!m) {
    const t = new Date(s).getTime();
    return isNaN(t) ? null : t;
  }
  const [, y, mo, d, hh, mm, ss] = m;
  return new Date(
    Number(y),
    Number(mo) - 1,
    Number(d),
    hh ? Number(hh) : 0,
    mm ? Number(mm) : 0,
    ss ? Number(ss) : 0,
  ).getTime();
}

function fmtDate(ts: number): string {
  const d = new Date(ts);
  const y = d.getFullYear();
  const mo = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  // 跨年显示年份，否则显示 MM-DD
  const jan1 = new Date(y, 0, 1).getTime();
  const nextJan1 = new Date(y + 1, 0, 1).getTime();
  if (rangeStart.value >= jan1 && rangeEnd.value <= nextJan1) {
    return `${mo}-${day}`;
  }
  return `${y}-${mo}-${day}`;
}

const DAY = 86400000;

// 仅纳入带时间窗（plan_start 或 plan_end）的计划；无时间的计划不画甘特
const timedPlans = computed(() =>
  props.plans.filter(
    (p) => parseISO(p.plan_start) != null || parseISO(p.plan_end) != null,
  ),
);

// 计算时间轴范围：覆盖所有计划的 plan_start~plan_end；若无则用今天±7天
const rangeStart = computed<number>(() => {
  const starts = timedPlans.value
    .map((p) => parseISO(p.plan_start))
    .filter((x): x is number => x != null);
  if (starts.length) {
    const min = Math.min(...starts);
    return new Date(min).setHours(0, 0, 0, 0);
  }
  return new Date().setHours(0, 0, 0, 0) - 7 * DAY;
});

const rangeEnd = computed<number>(() => {
  const ends = timedPlans.value
    .map((p) => parseISO(p.plan_end) ?? (parseISO(p.plan_start) ? parseISO(p.plan_start)! + DAY : null))
    .filter((x): x is number => x != null);
  if (ends.length) {
    const max = Math.max(...ends);
    const d = new Date(max);
    d.setHours(0, 0, 0, 0);
    return d.getTime() + DAY; // 含当天
  }
  return new Date().setHours(0, 0, 0, 0) + 7 * DAY;
});

const spanMs = computed(() => Math.max(1, rangeEnd.value - rangeStart.value));

// 每个计划的横条几何
const rows = computed(() =>
  timedPlans.value
    .map((p) => {
      const sRaw = parseISO(p.plan_start);
      const eRaw = parseISO(p.plan_end);
      const start = sRaw != null ? sRaw : rangeStart.value;
      const end = eRaw != null ? eRaw : sRaw != null ? sRaw + DAY : rangeEnd.value;
      const leftPct = ((Math.min(Math.max(start, rangeStart.value), rangeEnd.value) - rangeStart.value) / spanMs.value) * 100;
      const right = ((Math.min(Math.max(end, rangeStart.value), rangeEnd.value) - rangeStart.value) / spanMs.value) * 100;
      const widthPct = Math.max(1.5, right - leftPct);
      return { plan: p, start, end, leftPct, widthPct };
    })
    .sort((a, b) => a.start - b.start),
);

// 时间轴刻度（均匀 6 等分）
const ticks = computed(() => {
  const n = 6;
  const out: { pct: number; label: string }[] = [];
  for (let i = 0; i <= n; i++) {
    const ts = rangeStart.value + (spanMs.value * i) / n;
    out.push({ pct: (i / n) * 100, label: fmtDate(ts) });
  }
  return out;
});

// 当前时间竖线
const nowPct = computed<number | null>(() => {
  const now = Date.now();
  if (now < rangeStart.value || now > rangeEnd.value) return null;
  return ((now - rangeStart.value) / spanMs.value) * 100;
});

function statusClass(s: WorkPlanStatus): string {
  if (s === "执行中") return "st-run";
  if (s === "已完成") return "st-done";
  return "st-draft";
}

function barTitle(r: { plan: WorkPlan }): string {
  const p = r.plan;
  const dev = (p.devices || []).length;
  return `${p.name}｜${p.plan_start || "?"} ~ ${p.plan_end || "?"}｜设备 ${dev}｜${p.active ? "监控中" : p.status}`;
}
</script>

<template>
  <div class="gantt" v-if="rows.length">
    <div class="gantt-axis">
      <div class="gantt-axis-label">计划 / 时间</div>
      <div class="gantt-axis-track">
        <span
          v-for="(t, i) in ticks"
          :key="i"
          class="gantt-tick"
          :style="{ left: t.pct + '%' }"
          >{{ t.label }}</span
        >
      </div>
    </div>

    <!-- 计划条 -->
    <div class="gantt-body">
      <div
        v-for="r in rows"
        :key="r.plan.id"
        class="gantt-row"
        :title="barTitle(r)"
        @click="emit('select', r.plan)"
      >
        <div class="gantt-row-label" :title="r.plan.name">
          {{ r.plan.name }}
        </div>
        <div class="gantt-track">
          <div
            class="gantt-bar"
            :class="[
              r.plan.active ? 'is-active' : statusClass(r.plan.status),
            ]"
            :style="{ left: r.leftPct + '%', width: r.widthPct + '%' }"
          >
            <span class="gantt-bar-dev">设{{(r.plan.devices || []).length}}</span>
          </div>
          <div v-if="nowPct != null" class="gantt-now" :style="{ left: nowPct + '%' }" />
        </div>
      </div>
    </div>
  </div>
  <div v-else class="gantt-empty">暂无带时间窗的作业计划</div>
</template>

<style scoped>
.gantt {
  font-size: 13px;
}
.gantt-axis {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 4px;
  margin-bottom: 6px;
}
.gantt-axis-label {
  width: 180px;
  flex: 0 0 180px;
  color: #909399;
  font-size: 12px;
}
.gantt-axis-track {
  position: relative;
  flex: 1;
  height: 16px;
}
.gantt-tick {
  position: absolute;
  transform: translateX(-50%);
  color: #909399;
  font-size: 11px;
  white-space: nowrap;
}
.gantt-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.gantt-row {
  display: flex;
  align-items: center;
  cursor: pointer;
}
.gantt-row:hover .gantt-bar {
  filter: brightness(1.08);
}
.gantt-row-label {
  width: 180px;
  flex: 0 0 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 8px;
  color: #303133;
}
.gantt-track {
  position: relative;
  flex: 1;
  height: 24px;
  background: #f5f7fa;
  border-radius: 4px;
}
.gantt-bar {
  position: absolute;
  top: 3px;
  height: 18px;
  min-width: 6px;
  border-radius: 4px;
  background: #909399;
  display: flex;
  align-items: center;
  padding: 0 4px;
  box-sizing: border-box;
  color: #fff;
  font-size: 11px;
  overflow: hidden;
}
.gantt-bar.st-draft {
  background: #909399;
}
.gantt-bar.st-run {
  background: #e6a23c;
}
.gantt-bar.st-done {
  background: #67c23a;
}
.gantt-bar.is-active {
  background: #f56c6c;
  box-shadow: 0 0 0 1px #f56c6c inset;
}
.gantt-bar-dev {
  white-space: nowrap;
}
.gantt-now {
  position: absolute;
  top: -2px;
  width: 2px;
  height: 28px;
  background: #409eff;
  transform: translateX(-1px);
}
</style>
