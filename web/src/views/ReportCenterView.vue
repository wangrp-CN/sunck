<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  exportRiskHealthReport,
  getRiskHealthReportPreview,
  type RiskHealthPeriod,
  type RiskHealthReportPreview,
} from "@/api/reports";

const period = ref<RiskHealthPeriod>("weekly");
const loading = ref(false);
const exporting = ref<"" | "excel" | "pdf">("");
const data = ref<RiskHealthReportPreview | null>(null);

async function load() {
  loading.value = true;
  try {
    data.value = await getRiskHealthReportPreview({ period_type: period.value });
  } catch (e) {
    ElMessage.error("加载风险健康报表失败");
    data.value = null;
  } finally {
    loading.value = false;
  }
}

function riskTag(riskLevel: string | null): "" | "danger" | "warning" | "success" {
  if (riskLevel === "高") return "danger";
  if (riskLevel === "中") return "warning";
  if (riskLevel === "低") return "success";
  return "";
}

function healthTag(level: string | null): "" | "success" | "warning" | "danger" {
  if (level === "优") return "success";
  if (level === "中") return "warning";
  if (level === "差") return "danger";
  return "";
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function doExport(fmt: "excel" | "pdf") {
  exporting.value = fmt;
  try {
    const blob = await exportRiskHealthReport(fmt, { period_type: period.value });
    const ext = fmt === "pdf" ? "pdf" : "xlsx";
    triggerDownload(blob, `风险健康报表_${period.value}.${ext}`);
    ElMessage.success("报表已导出");
  } catch (e) {
    ElMessage.error("导出失败");
  } finally {
    exporting.value = "";
  }
}

onMounted(load);
</script>

<template>
  <div class="report-center" v-loading="loading">
    <el-card shadow="never" class="toolbar">
      <div class="toolbar-row">
        <el-radio-group v-model="period" @change="load">
          <el-radio-button value="weekly">周报（上周）</el-radio-button>
          <el-radio-button value="daily">日报（昨日）</el-radio-button>
        </el-radio-group>
        <div class="spacer" />
        <el-button
          type="primary"
          :loading="exporting === 'excel'"
          @click="doExport('excel')"
          >导出 Excel</el-button
        >
        <el-button
          :loading="exporting === 'pdf'"
          @click="doExport('pdf')"
          >导出 PDF</el-button
        >
      </div>
      <div v-if="data" class="range-hint">
        统计周期：{{ data.range_start.slice(0, 10) }} ~ {{ data.range_end.slice(0, 10) }}
      </div>
    </el-card>

    <template v-if="data">
      <!-- 概览 -->
      <el-row :gutter="16" class="stat-row">
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-num">{{ data.summary.project_count }}</div>
            <div class="stat-label">纳入项目</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-num">{{ data.summary.avg_risk ?? "—" }}</div>
            <div class="stat-label">平均风险分</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card danger">
            <div class="stat-num">{{ data.summary.high_risk_count }}</div>
            <div class="stat-label">高风险项目</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-num">{{ data.summary.device_count }}</div>
            <div class="stat-label">纳入设备</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-num">{{ data.summary.avg_health ?? "—" }}</div>
            <div class="stat-label">平均健康分</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card danger">
            <div class="stat-num">{{ data.summary.offline_count }}</div>
            <div class="stat-label">离线设备</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <!-- 项目风险排名 -->
        <el-col :span="14">
          <el-card shadow="never" header="项目风险排名（最新 + 环比）">
            <el-table :data="data.project_rows" border stripe size="small" max-height="420">
              <el-table-column prop="name" label="项目" min-width="140" />
              <el-table-column prop="risk_level" label="等级" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="riskTag(row.risk_level)" size="small">{{ row.risk_level }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="risk_index" label="风险分" width="90" align="center" />
              <el-table-column prop="prev_risk_index" label="上期" width="80" align="center" />
              <el-table-column label="环比Δ" width="90" align="center">
                <template #default="{ row }">
                  <span v-if="row.delta === null">新</span>
                  <span v-else :class="row.delta > 0 ? 'up' : row.delta < 0 ? 'down' : ''">
                    {{ row.delta > 0 ? "+" : "" }}{{ row.delta }}
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>

        <!-- 设备健康分布 -->
        <el-col :span="10">
          <el-card shadow="never" header="设备健康分布（最新）">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="健康(优/良/中/差)">
                {{ data.summary.health_dist["优"] }}/{{ data.summary.health_dist["良"] }}/{{
                  data.summary.health_dist["中"]
                }}/{{ data.summary.health_dist["差"] }}
              </el-descriptions-item>
              <el-descriptions-item label="在线(在线/延迟/离线)">
                {{ data.summary.online_dist.fresh }}/{{ data.summary.online_dist.stale }}/{{
                  data.summary.online_dist.offline
                }}
              </el-descriptions-item>
            </el-descriptions>
            <div class="sub-title">亚健康 Top（健康分最低）</div>
            <el-table :data="data.top_unhealthy_devices" border stripe size="small" max-height="300">
              <el-table-column prop="name" label="设备" min-width="120" />
              <el-table-column prop="health_level" label="等级" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="healthTag(row.health_level)" size="small">{{ row.health_level }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="health_score" label="健康分" width="90" align="center" />
              <el-table-column prop="online_state" label="状态" width="80" align="center" />
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else-if="!loading" description="暂无快照数据，请先运行定时快照任务" />
  </div>
</template>

<style scoped>
.report-center {
  padding: 16px;
}
.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.spacer {
  flex: 1;
}
.range-hint {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
}
.stat-row {
  margin: 16px 0;
}
.stat-card {
  text-align: center;
}
.stat-card.danger :deep(.stat-num) {
  color: #f56c6c;
}
.stat-num {
  font-size: 26px;
  font-weight: 700;
}
.stat-label {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}
.sub-title {
  margin: 12px 0 6px;
  font-weight: 600;
  font-size: 13px;
}
.up {
  color: #f56c6c;
}
.down {
  color: #67c23a;
}
</style>
