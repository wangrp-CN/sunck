<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { listUsers } from "@/api/user";
import {
  dispatchAction,
  getDispatchOptions,
  getDispatchStats,
  listDispatches,
  reassignDispatch,
  type DispatchOptions,
  type DispatchOrder,
  type DispatchStats,
} from "@/api/dispatch";
import DispatchCreateDialog from "@/components/DispatchCreateDialog.vue";

const auth = useAuthStore();
const canCreate = computed(() => auth.hasPermission("dispatch:create"));
const canHandle = computed(() => auth.hasPermission("dispatch:handle"));

const items = ref<DispatchOrder[]>([]);
const total = ref(0);
const stats = ref<DispatchStats>({ total: 0, by_status: {}, by_level: {} });
const options = ref<DispatchOptions>({ statuses: [], sources: [], levels: [] });
const loading = ref(false);
const page = ref(1);
const size = ref(20);
const filterStatus = ref<string>("");
const filterSource = ref<string>("");
const createVisible = ref(false);

const reassignVisible = ref(false);
const reassignTarget = ref<DispatchOrder | null>(null);
const users = ref<{ id: number; name: string }[]>([]);
const reassignUserId = ref<number | null>(null);
const reassignNote = ref("");

async function load() {
  loading.value = true;
  try {
    const [list, st, opt] = await Promise.all([
      listDispatches({
        status: filterStatus.value || undefined,
        source_type: filterSource.value || undefined,
        page: page.value,
        size: size.value,
      }),
      getDispatchStats().catch(() => ({ total: 0, by_status: {}, by_level: {} })),
      getDispatchOptions().catch(() => ({ statuses: [], sources: [], levels: [] })),
    ]);
    items.value = list.items;
    total.value = list.total;
    stats.value = st;
    options.value = opt;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载派单失败");
  } finally {
    loading.value = false;
  }
}

function statusTag(status: string): "" | "success" | "warning" | "primary" | "info" {
  if (status === "已闭环") return "success";
  if (status === "处理中") return "primary";
  if (status === "待派") return "warning";
  return "info";
}

async function doAction(row: DispatchOrder, action: string, note?: string) {
  try {
    await dispatchAction(row.id, action, note);
    ElMessage.success(action === "close" ? "已闭环" : "已更新");
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

async function openReassign(row: DispatchOrder) {
  reassignTarget.value = row;
  reassignUserId.value = row.assignee_id;
  reassignNote.value = "";
  reassignVisible.value = true;
  try {
    const r = await listUsers({ page: 1, size: 200 });
    users.value = (r.items || []).map((u: any) => ({ id: u.id, name: u.nickname || u.username }));
  } catch {
    users.value = [];
  }
}

async function submitReassign() {
  if (!reassignTarget.value || !reassignUserId.value) {
    ElMessage.warning("请选择新处理人");
    return;
  }
  try {
    await reassignDispatch(reassignTarget.value.id, reassignUserId.value, reassignNote.value || undefined);
    ElMessage.success("已改派");
    reassignVisible.value = false;
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "改派失败");
  }
}

onMounted(load);
</script>

<template>
  <div class="page">
    <div class="bar">
      <span class="title">根因派单闭环</span>
      <div class="stats">
        <span>共 {{ stats.total }} 单</span>
        <span class="s-warning">待派 {{ stats.by_status["待派"] || 0 }}</span>
        <span class="s-primary">处理中 {{ stats.by_status["处理中"] || 0 }}</span>
        <span class="s-success">已闭环 {{ stats.by_status["已闭环"] || 0 }}</span>
      </div>
      <el-button v-if="canCreate" type="primary" @click="createVisible = true">新建派单</el-button>
    </div>

    <div class="filters">
      <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 140px" @change="load">
        <el-option v-for="s in options.statuses" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="filterSource" placeholder="来源" clearable style="width: 140px" @change="load">
        <el-option v-for="s in options.sources" :key="s" :label="s" :value="s" />
      </el-select>
    </div>

    <el-table :data="items" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="160" />
      <el-table-column label="来源" width="150">
        <template #default="{ row }">
          <span>{{ row.source_type }}</span>
          <span v-if="row.source_id" class="muted">#{{ row.source_id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="project_id" label="项目" width="80" />
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.level" size="small">{{ row.level }}</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="assignee_name" label="处理人" width="110" />
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canHandle && row.status === '待派'"
            size="small"
            type="primary"
            @click="doAction(row, 'start')"
            >开始处理</el-button
          >
          <el-button
            v-if="canHandle && row.status === '处理中'"
            size="small"
            type="success"
            @click="doAction(row, 'close')"
            >闭环</el-button
          >
          <el-button v-if="canHandle" size="small" @click="openReassign(row)">改派</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无派单</template>
    </el-table>

    <el-pagination
      class="pager"
      :current-page="page"
      :page-size="size"
      :total="total"
      layout="prev, pager, next, total"
      @current-change="(p: number) => { page = p; load(); }"
    />

    <DispatchCreateDialog v-model="createVisible" @created="load" />

    <el-dialog v-model="reassignVisible" title="改派处理人" width="420px">
      <el-form label-width="80px">
        <el-form-item label="新处理人">
          <el-select v-model="reassignUserId as any" filterable style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="reassignNote" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reassignVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReassign">确认改派</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 15px; font-weight: 600; color: #303133; }
.stats { display: flex; gap: 12px; font-size: 13px; color: #606266; }
.s-warning { color: #e6a23c; }
.s-primary { color: #409eff; }
.s-success { color: #67c23a; }
.filters { display: flex; gap: 10px; margin-bottom: 12px; }
.muted { color: #c0c4cc; font-size: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
</style>
