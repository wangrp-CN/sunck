<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  fetchAuditLogs,
  fetchAuditMeta,
  type AuditLogItem,
  type AuditMeta,
} from "@/api/audit";

const loading = ref(false);
const list = ref<AuditLogItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

const meta = ref<AuditMeta>({ modules: [], actions: [] });
const filters = reactive({
  module: "",
  action: "",
  username: "",
  dateRange: [] as string[],
});

const ACTION_TAG: Record<string, string> = {
  create: "success",
  update: "warning",
  delete: "danger",
  other: "info",
};

async function loadMeta() {
  try {
    meta.value = await fetchAuditMeta();
  } catch {
    // 静默：下拉仅为便利
  }
}

async function loadData() {
  loading.value = true;
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      size: size.value,
    };
    if (filters.module) params.module = filters.module;
    if (filters.action) params.action = filters.action;
    if (filters.username) params.username = filters.username;
    if (filters.dateRange?.length === 2) {
      params.start = filters.dateRange[0];
      params.end = filters.dateRange[1];
    }
    const data = await fetchAuditLogs(params);
    list.value = data.items ?? [];
    total.value = data.total ?? 0;
  } catch (e: unknown) {
    const msg = (e as { message?: string })?.message || "加载审计日志失败";
    ElMessage.error(msg);
  } finally {
    loading.value = false;
  }
}

function onSearch() {
  page.value = 1;
  loadData();
}

function onReset() {
  filters.module = "";
  filters.action = "";
  filters.username = "";
  filters.dateRange = [];
  page.value = 1;
  loadData();
}

function onPageChange(p: number) {
  page.value = p;
  loadData();
}

function actionTag(action: string): string {
  return ACTION_TAG[action] ?? "info";
}

onMounted(() => {
  loadMeta();
  loadData();
});
</script>

<template>
  <div class="audit-view">
    <el-card shadow="never" class="filter-card">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="模块">
          <el-select
            v-model="filters.module"
            placeholder="全部模块"
            clearable
            style="width: 160px"
          >
            <el-option v-for="m in meta.modules" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="动作">
          <el-select
            v-model="filters.action"
            placeholder="全部动作"
            clearable
            style="width: 140px"
          >
            <el-option v-for="a in meta.actions" :key="a" :label="a" :value="a" />
          </el-select>
        </el-form-item>
        <el-form-item label="操作人">
          <el-input
            v-model="filters.username"
            placeholder="账号关键字"
            clearable
            style="width: 160px"
          />
        </el-form-item>
        <el-form-item label="时间">
          <el-date-picker
            v-model="filters.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="onSearch">查询</el-button>
          <el-button @click="onReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe border height="100%">
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column prop="username" label="操作人" width="140">
          <template #default="{ row }">
            <span>{{ row.username || "匿名" }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="module" label="模块" width="140" />
        <el-table-column prop="action" label="动作" width="110">
          <template #default="{ row }">
            <el-tag :type="actionTag(row.action)" size="small">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="path" label="路径" min-width="240" show-overflow-tooltip />
        <el-table-column prop="status_code" label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status_code < 400 ? 'success' : 'danger'" size="small">
              {{ row.status_code }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="来源IP" width="150" />
      </el-table>

      <div class="pager">
        <el-pagination
          :current-page="page"
          :page-size="size"
          :total="total"
          layout="total, prev, pager, next, jumper"
          background
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.audit-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
}
.table-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.table-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
