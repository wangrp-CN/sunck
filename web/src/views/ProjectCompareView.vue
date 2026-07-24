<script setup lang="ts">
import { onMounted, ref } from "vue";
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

// 风险分档：直接采用后端 risk_level（高/中/低），不再用前端阈值复算
function riskLevelTag(level?: string | null): "" | "success" | "warning" | "danger" {
  switch (level) {
    case "高":
      return "danger";
    case "中":
      return "warning";
    case "低":
      return "success";
    default:
      return "";
  }
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
      <el-table-column label="风险分" min-width="240">
        <template #default="{ row }">
          <div class="risk-bar-wrap">
            <div class="risk-bar" :class="riskLevelTag(row.risk_level)" :style="{ width: (row.risk_index || 0) + '%' }"></div>
            <span class="risk-score" :class="riskLevelTag(row.risk_level)">{{ row.risk_index ?? 0 }}</span>
            <el-tag :type="riskLevelTag(row.risk_level)" size="small" style="margin-left: 6px">
              {{ row.risk_level || "—" }}
            </el-tag>
          </div>
          <div class="risk-raw">原始分 {{ row.risk_score }}</div>
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
.risk-raw { font-size: 12px; color: #909399; margin-top: 2px; }
</style>
