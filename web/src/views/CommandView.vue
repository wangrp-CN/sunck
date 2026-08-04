<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { listCommands, retryCommand } from "@/api/command";
import type { DeviceCommand } from "@/types";

const DEVICE_TYPE_LABELS: Record<string, string> = {
  locate: "人机定位",
  anti_intrusion: "大机防侵限",
  train_approach: "列车接近",
};
function typeLabel(t: string): string {
  return DEVICE_TYPE_LABELS[t] || t;
}

const STATUS_META: Record<string, { label: string; tag: "primary" | "success" | "danger" | "info" }> = {
  pending: { label: "待发送", tag: "info" },
  sent: { label: "已下发", tag: "primary" },
  acked: { label: "已回执", tag: "success" },
  failed: { label: "失败", tag: "danger" },
};
function statusMeta(s: string) {
  return STATUS_META[s] || { label: s, tag: "info" as const };
}

const loading = ref(false);
const rows = ref<DeviceCommand[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

const filters = reactive({
  device_no: "",
  device_type: "",
  status: "",
});

const pagedTotal = computed(() => total.value);

async function load() {
  loading.value = true;
  try {
    const res = await listCommands({
      device_no: filters.device_no || undefined,
      device_type: filters.device_type || undefined,
      status: filters.status || undefined,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载指令记录失败");
  } finally {
    loading.value = false;
  }
}

function onFilter() {
  page.value = 1;
  load();
}
function onReset() {
  filters.device_no = "";
  filters.device_type = "";
  filters.status = "";
  page.value = 1;
  load();
}
async function onRetry(row: DeviceCommand) {
  try {
    await retryCommand(row.id);
    ElMessage.success(`已重新下发指令 #${row.id}`);
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "重试失败");
  }
}

onMounted(load);
</script>

<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="panel-head">
          <span>指令下发记录</span>
          <span class="hint">每次平台→设备下行指令均留痕，可追踪下发/回执/重试状态</span>
        </div>
      </template>

      <div class="filters">
        <el-input v-model="filters.device_no" placeholder="设备编号" clearable style="width: 160px" @keyup.enter="onFilter" />
        <el-select v-model="filters.device_type" placeholder="设备类型" clearable style="width: 150px">
          <el-option label="人机定位" value="locate" />
          <el-option label="大机防侵限" value="anti_intrusion" />
          <el-option label="列车接近" value="train_approach" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 130px">
          <el-option label="待发送" value="pending" />
          <el-option label="已下发" value="sent" />
          <el-option label="已回执" value="acked" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button type="primary" @click="onFilter">查询</el-button>
        <el-button @click="onReset">重置</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="设备编号" prop="device_no" min-width="130" />
        <el-table-column label="设备类型" width="120">
          <template #default="{ row }">{{ typeLabel(row.device_type) }}</template>
        </el-table-column>
        <el-table-column prop="action" label="动作" width="150" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).tag" effect="light">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="重试" width="70" prop="retry_count" />
        <el-table-column label="关联告警" width="100">
          <template #default="{ row }">{{ row.alarm_id != null ? "#" + row.alarm_id : "—" }}</template>
        </el-table-column>
        <el-table-column label="下发时间" width="170">
          <template #default="{ row }">{{ row.sent_at || "—" }}</template>
        </el-table-column>
        <el-table-column label="回执时间" width="170">
          <template #default="{ row }">{{ row.acked_at || "—" }}</template>
        </el-table-column>
        <el-table-column label="说明/错误" min-width="200">
          <template #default="{ row }">
            <span v-if="row.last_error" class="err">{{ row.last_error }}</span>
            <span v-else-if="row.params_json" class="params">{{ JSON.stringify(row.params_json) }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'acked'"
              link
              type="primary"
              @click="onRetry(row)"
            >重试</el-button>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination :current-page="page" :page-size="size" :total="pagedTotal" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next, jumper" @size-change="(s: number) => { size = s; }" @current-change="(p: number) => { page = p; load(); }" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.hint { font-size: 12px; color: #909399; font-weight: normal; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.err { color: #f56c6c; font-size: 12px; }
.params { color: #606266; font-size: 12px; word-break: break-all; }
</style>
