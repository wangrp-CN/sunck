<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import { getProjectCompare } from "@/api/dashboard";
import type { ProjectCompareResp } from "@/types";

const auth = useAuthStore();

const days = ref(7);
const resp = ref<ProjectCompareResp | null>(null);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    resp.value = await getProjectCompare(days.value);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载对比数据失败");
  } finally {
    loading.value = false;
  }
}

function riskTag(score: number): "" | "success" | "warning" | "danger" {
  if (score === 0) return "success";
  if (score < 5) return "warning";
  return "danger";
}
function riskText(score: number): string {
  if (score === 0) return "低风险";
  if (score < 5) return "中风险";
  return "高风险";
}

const maxRisk = computed(() =>
  Math.max(1, ...(resp.value?.items || []).map((i) => i.risk_score)),
);
function riskWidth(score: number): string {
  return `${(score / maxRisk.value) * 100}%`;
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* ignore */
    }
  }
  await load();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <span class="title">多项目横向对比（按风险分降序）</span>
      <el-radio-group v-model="days" @change="load">
        <el-radio-button :value="7">近 7 天</el-radio-button>
        <el-radio-button :value="30">近 30 天</el-radio-button>
        <el-radio-button :value="90">近 90 天</el-radio-button>
      </el-radio-group>
    </div>

    <el-table :data="resp?.items || []" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="project_name" label="项目" min-width="150" />
      <el-table-column label="设备/人/机/栏" width="170">
        <template #default="{ row }">
          <span class="cnt">设{{ row.device_count }}</span>
          <span class="cnt">人{{ row.person_count }}</span>
          <span class="cnt">机{{ row.machine_count }}</span>
          <span class="cnt">栏{{ row.fence_count }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="active_plan_count" label="在执行计划" width="110" />
      <el-table-column prop="alarm_count" label="窗口告警" width="100" />
      <el-table-column prop="unhandled_alarm_count" label="未处理" width="100">
        <template #default="{ row }">
          <span :class="{ danger: row.unhandled_alarm_count > 0 }">{{ row.unhandled_alarm_count }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="open_hazard_count" label="存量隐患" width="100" />
      <el-table-column prop="overdue_hazard_count" label="超期隐患" width="100">
        <template #default="{ row }">
          <span :class="{ danger: row.overdue_hazard_count > 0 }">{{ row.overdue_hazard_count }}</span>
        </template>
      </el-table-column>
      <el-table-column label="风险分" min-width="200">
        <template #default="{ row }">
          <div class="risk-bar-wrap">
            <div class="risk-bar" :class="riskTag(row.risk_score)" :style="{ width: riskWidth(row.risk_score) }"></div>
            <span class="risk-score" :class="riskTag(row.risk_score)">{{ row.risk_score }}</span>
            <el-tag :type="riskTag(row.risk_score)" size="small" style="margin-left: 6px">
              {{ riskText(row.risk_score) }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <template #empty>暂无项目数据</template>
    </el-table>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 15px; font-weight: 600; color: #303133; }
.cnt { margin-right: 6px; font-size: 12px; color: #606266; }
.danger { color: #f56c6c; font-weight: 600; }
.risk-bar-wrap { display: flex; align-items: center; gap: 8px; }
.risk-bar { height: 14px; border-radius: 7px; min-width: 4px; }
.risk-bar.success { background: #67c23a; }
.risk-bar.warning { background: #e6a23c; }
.risk-bar.danger { background: #f56c6c; }
.risk-score { font-weight: 700; }
.risk-score.success { color: #67c23a; }
.risk-score.warning { color: #e6a23c; }
.risk-score.danger { color: #f56c6c; }
</style>
