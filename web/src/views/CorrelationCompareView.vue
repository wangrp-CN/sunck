<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getCorrelationCompare } from "@/api/metrics";
import CorrelationHeatmap from "@/components/CorrelationHeatmap.vue";
import type { CorrelationCompareResp } from "@/api/metrics";

// 对比大屏关联热力：两个时间窗（A vs B）的跨设备共因空间热力对比。
// 后端在各自窗口内对原始告警重算聚类（不依赖派生滚动表），并给出
// 新增 / 消失 / 增强减弱 的变化摘要，揭示共因热点的时段迁移。

const rangeA = ref<[Date, Date] | null>(null);
const rangeB = ref<[Date, Date] | null>(null);
const onlyCross = ref(true);
const loading = ref(false);
const resp = ref<CorrelationCompareResp | null>(null);

// 本地墙钟 → 朴素 ISO（无时区后缀），后端按业务时区 Asia/Shanghai 归一处理
function fmtLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function daysAgo(n: number): Date {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d;
}

async function load() {
  if (!rangeA.value || !rangeB.value) {
    ElMessage.warning("请先选择两个对比时间窗");
    return;
  }
  loading.value = true;
  try {
    resp.value = await getCorrelationCompare({
      start_a: fmtLocal(rangeA.value[0]),
      end_a: fmtLocal(rangeA.value[1]),
      start_b: fmtLocal(rangeB.value[0]),
      end_b: fmtLocal(rangeB.value[1]),
      only_cross_device: onlyCross.value,
    });
  } catch (e: any) {
    ElMessage.error(e?.message || "对比加载失败");
  } finally {
    loading.value = false;
  }
}

// 变化摘要：增强/减弱按绝对变化量降序，突出最显著的迁移
const changedSorted = computed(() =>
  (resp.value?.diff.changed || [])
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

onMounted(() => {
  const now = new Date();
  rangeA.value = [daysAgo(7), now]; // 近期：近 7 天
  rangeB.value = [daysAgo(14), daysAgo(7)]; // 基线：前 7 天
  load();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <span class="title">关联热力对比（时间窗 A vs B）</span>
      <div class="ctrls">
        <el-date-picker
          v-model="rangeA"
          type="datetimerange"
          range-separator="至"
          start-placeholder="窗口A 开始"
          end-placeholder="窗口A 结束"
          size="small"
          @change="load"
        />
        <span class="vs">对比</span>
        <el-date-picker
          v-model="rangeB"
          type="datetimerange"
          range-separator="至"
          start-placeholder="窗口B 开始"
          end-placeholder="窗口B 结束"
          size="small"
          @change="load"
        />
        <el-switch
          v-model="onlyCross"
          active-text="仅跨设备"
          inactive-text="全部"
          size="small"
          @change="load"
        />
        <el-button type="primary" size="small" :loading="loading" @click="load">
          对比
        </el-button>
      </div>
    </div>

    <div v-loading="loading">
      <template v-if="resp">
        <!-- 两窗热力并排 -->
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" class="hm-card">
              <template #header>
                <div class="hm-head">
                  <span class="hm-title">窗口 A（{{ fmtRange(resp.window_a.start, resp.window_a.end) }}）</span>
                  <span class="hm-meta">
                    热点 {{ resp.window_a.total }} · 跨设备 {{ resp.window_a.cross_device_total }} · 告警 {{ resp.window_a.alarm_total }}
                  </span>
                </div>
              </template>
              <CorrelationHeatmap :points="resp.window_a.points" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" class="hm-card">
              <template #header>
                <div class="hm-head">
                  <span class="hm-title">窗口 B（{{ fmtRange(resp.window_b.start, resp.window_b.end) }}）</span>
                  <span class="hm-meta">
                    热点 {{ resp.window_b.total }} · 跨设备 {{ resp.window_b.cross_device_total }} · 告警 {{ resp.window_b.alarm_total }}
                  </span>
                </div>
              </template>
              <CorrelationHeatmap :points="resp.window_b.points" />
            </el-card>
          </el-col>
        </el-row>

        <!-- 变化摘要 -->
        <el-card shadow="never" class="diff-card">
          <template #header>
            <div class="diff-head">
              <span class="diff-title">共因热点变化摘要</span>
              <el-tag size="small" effect="plain">共 {{ diffTotal }} 处变化</el-tag>
            </div>
          </template>

          <el-empty v-if="diffTotal === 0" description="两个时间窗的共因热点无变化" :image-size="48" />

          <div v-else class="diff-body">
            <div v-if="resp.diff.new.length" class="diff-block">
              <div class="diff-sub new">新增热点（仅 B 窗出现）· {{ resp.diff.new.length }}</div>
              <ul class="diff-list">
                <li v-for="it in resp.diff.new" :key="it.key" class="diff-item">
                  <span class="dot new" />
                  <span class="scope">{{ it.scope_text }}</span>
                  <span class="proj">{{ it.project_name || "—" }}</span>
                  <span class="cnt">告警 {{ it.weight }}</span>
                  <span class="lv" v-if="it.max_level">{{ it.max_level }}</span>
                </li>
              </ul>
            </div>

            <div v-if="resp.diff.removed.length" class="diff-block">
              <div class="diff-sub removed">消失热点（仅 A 窗出现）· {{ resp.diff.removed.length }}</div>
              <ul class="diff-list">
                <li v-for="it in resp.diff.removed" :key="it.key" class="diff-item">
                  <span class="dot removed" />
                  <span class="scope">{{ it.scope_text }}</span>
                  <span class="proj">{{ it.project_name || "—" }}</span>
                  <span class="cnt">告警 {{ it.weight }}</span>
                  <span class="lv" v-if="it.max_level">{{ it.max_level }}</span>
                </li>
              </ul>
            </div>

            <div v-if="resp.diff.changed.length" class="diff-block">
              <div class="diff-sub changed">增强 / 减弱（两窗均有）· {{ resp.diff.changed.length }}</div>
              <ul class="diff-list">
                <li v-for="it in changedSorted" :key="it.key" class="diff-item">
                  <span class="dot changed" />
                  <span class="scope">{{ it.scope_text }}</span>
                  <span class="proj">{{ it.project_name || "—" }}</span>
                  <span class="cnt">
                    A {{ it.a_weight }} → B {{ it.b_weight }}
                  </span>
                  <el-tag :type="deltaTag(it.delta || 0)" size="small" effect="light">
                    {{ it.delta! > 0 ? "+" : "" }}{{ it.delta }}
                  </el-tag>
                </li>
              </ul>
            </div>
          </div>
        </el-card>
      </template>

      <el-empty v-else description="请选择时间窗后点击「对比」" :image-size="60" />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}
.title { font-size: 15px; font-weight: 600; color: #303133; }
.ctrls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.vs { color: #909399; font-size: 13px; }
.hm-card { margin-bottom: 12px; }
.hm-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.hm-title { font-size: 14px; font-weight: 600; color: #303133; }
.hm-meta { font-size: 12px; color: #909399; }
.diff-card { margin-bottom: 12px; }
.diff-head { display: flex; align-items: center; gap: 10px; }
.diff-title { font-size: 14px; font-weight: 600; color: #303133; }
.diff-body { display: flex; flex-direction: column; gap: 14px; }
.diff-block { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px 12px; }
.diff-sub { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.diff-sub.new { color: #2f9e8f; }
.diff-sub.removed { color: #909399; }
.diff-sub.changed { color: #e6a23c; }
.diff-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.diff-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #606266; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot.new { background: #2f9e8f; }
.dot.removed { background: #c0c4cc; }
.dot.changed { background: #e6a23c; }
.scope { font-weight: 600; color: #303133; }
.proj { color: #909399; }
.cnt { margin-left: auto; color: #606266; }
.lv { color: #f56c6c; }
</style>
