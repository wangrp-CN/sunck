<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import {
  fetchInspectionStats,
  fetchInspectionTasks,
  fetchInspectionTask,
  createInspectionTask,
  updateInspectionTask,
  deleteInspectionTask,
  transitionInspectionTask,
  checkinInspectionTask,
  convertCheckinToHazard,
} from "@/api/inspection";
import { fetchProjects } from "@/api/project";
import { listUsers } from "@/api/user";
import type { InspectionTask, InspectionStats, Project, SysUser } from "@/types";

const auth = useAuthStore();
const canAdd = computed(() => auth.user?.permission_codes.includes("inspection:create") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("inspection:update") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("inspection:delete") ?? false);
const canCheckin = computed(() => auth.user?.permission_codes.includes("inspection:checkin") ?? false);

const STATUS_OPTIONS = ["待巡检", "巡检中", "已完成", "已取消"];

const stats = ref<InspectionStats | null>(null);
const projects = ref<Project[]>([]);
const users = ref<SysUser[]>([]);
const list = ref<InspectionTask[]>([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const size = ref(20);
const filters = reactive({ project_id: null as number | null, status: "", keyword: "" });

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* ignore */
  }
}
async function loadUsers() {
  try {
    const res = await listUsers({ page: 1, size: 500 });
    users.value = res.items;
  } catch {
    /* ignore */
  }
}
async function loadStats() {
  try {
    stats.value = await fetchInspectionStats();
  } catch {
    /* ignore */
  }
}
async function loadTasks() {
  loading.value = true;
  try {
    const res = await fetchInspectionTasks({
      project_id: filters.project_id ?? undefined,
      status: filters.status || undefined,
      keyword: filters.keyword || undefined,
      page: page.value,
      size: size.value,
    });
    list.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载巡检任务失败");
  } finally {
    loading.value = false;
  }
}
function search() {
  page.value = 1;
  loadTasks();
}
function reset() {
  filters.project_id = null;
  filters.status = "";
  filters.keyword = "";
  search();
}
function pageChange(p: number) {
  page.value = p;
  loadTasks();
}

function projectName(id?: number | null) {
  if (id == null) return "—";
  return projects.value.find((p) => p.id === id)?.name ?? `ID:${id}`;
}
function userName(id?: number | null) {
  if (id == null) return "—";
  return users.value.find((u) => u.id === id)?.nickname || users.value.find((u) => u.id === id)?.username || `ID:${id}`;
}
function statusTag(s: string): "" | "info" | "success" | "warning" | "danger" {
  if (s === "巡检中") return "warning";
  if (s === "已完成") return "success";
  if (s === "待巡检") return "info";
  if (s === "已取消") return "danger";
  return "";
}
function transitionActions(s: string): ("start" | "finish" | "cancel")[] {
  if (s === "待巡检") return ["start"];
  if (s === "巡检中") return ["finish", "cancel"];
  return [];
}

// ---- 创建/编辑 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<number | null>(null);
const saving = ref(false);
const form = reactive({
  project_id: null as number | null,
  name: "",
  content: "" as string | null,
  assignee_id: null as number | null,
  start_time: "" as string | null,
  end_time: "" as string | null,
  required_checkins: 1,
});

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, {
    project_id: null,
    name: "",
    content: null,
    assignee_id: null,
    start_time: null,
    end_time: null,
    required_checkins: 1,
  });
  dialogVisible.value = true;
}
async function openEdit(row: InspectionTask) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    project_id: row.project_id ?? null,
    name: row.name,
    content: row.content ?? null,
    assignee_id: row.assignee_id ?? null,
    start_time: row.start_time ?? null,
    end_time: row.end_time ?? null,
    required_checkins: row.required_checkins,
  });
  dialogVisible.value = true;
}
async function submit() {
  if (!form.name) {
    ElMessage.warning("请输入任务名称");
    return;
  }
  saving.value = true;
  try {
    const req = {
      project_id: form.project_id,
      name: form.name,
      content: form.content || null,
      assignee_id: form.assignee_id,
      start_time: form.start_time || null,
      end_time: form.end_time || null,
      required_checkins: form.required_checkins,
    };
    if (dialogMode.value === "create") await createInspectionTask(req);
    else await updateInspectionTask(editingId.value!, req);
    ElMessage.success(dialogMode.value === "create" ? "已创建" : "已更新");
    dialogVisible.value = false;
    loadTasks();
    loadStats();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}
async function handleDelete(row: InspectionTask) {
  try {
    await ElMessageBox.confirm(`确认删除巡检任务「${row.name}」？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await deleteInspectionTask(row.id);
    ElMessage.success("已删除");
    loadTasks();
    loadStats();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}
async function doTransition(row: InspectionTask, action: "start" | "finish" | "cancel") {
  try {
    await transitionInspectionTask(row.id, action);
    ElMessage.success("状态已更新");
    loadTasks();
    loadStats();
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

// ---- 详情 + 打卡 + 转隐患 ----
const detailVisible = ref(false);
const detail = ref<InspectionTask | null>(null);
async function openDetail(row: InspectionTask) {
  try {
    detail.value = await fetchInspectionTask(row.id);
    detailVisible.value = true;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载详情失败");
  }
}
const checkinForm = reactive({
  result: "正常",
  note: "" as string | null,
  lng: null as number | null,
  lat: null as number | null,
});
function resetCheckinForm() {
  checkinForm.result = "正常";
  checkinForm.note = null;
  checkinForm.lng = null;
  checkinForm.lat = null;
}
async function submitCheckin() {
  if (!detail.value) return;
  try {
    await checkinInspectionTask(detail.value.id, {
      result: checkinForm.result,
      note: checkinForm.note || null,
      lng: checkinForm.lng,
      lat: checkinForm.lat,
    });
    ElMessage.success("打卡成功");
    resetCheckinForm();
    detail.value = await fetchInspectionTask(detail.value.id);
    loadTasks();
    loadStats();
  } catch (e: any) {
    ElMessage.error(e?.message || "打卡失败");
  }
}
async function toHazard(recordId: number) {
  try {
    const res = await convertCheckinToHazard(recordId);
    ElMessage.success(`已转为隐患（ID:${res.hazard_id}）`);
    if (detail.value) detail.value = await fetchInspectionTask(detail.value.id);
  } catch (e: any) {
    ElMessage.error(e?.message || "转隐患失败");
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
  await loadProjects();
  await loadUsers();
  await loadStats();
  await loadTasks();
});
</script>

<template>
  <div class="page">
    <!-- 统计卡片 -->
    <div class="stat-row" v-if="stats">
      <el-card shadow="never" class="stat-card">
        <div class="stat-num">{{ stats.task_total }}</div>
        <div class="stat-label">任务总数</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-num warning">{{ stats.by_status["巡检中"] || 0 }}</div>
        <div class="stat-label">巡检中</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-num info">{{ stats.by_status["待巡检"] || 0 }}</div>
        <div class="stat-label">待巡检</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-num">{{ stats.checkin_total }}</div>
        <div class="stat-label">打卡总数</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-num danger">{{ stats.abnormal_total }}</div>
        <div class="stat-label">异常打卡</div>
      </el-card>
    </div>

    <div class="bar">
      <el-form :inline="true" class="filters">
        <el-form-item label="项目">
          <el-select v-model="filters.project_id" placeholder="全部" clearable style="width: 160px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width: 120px">
            <el-option v-for="s in STATUS_OPTIONS" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="filters.keyword" placeholder="任务名称" clearable style="width: 160px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
      <el-button v-if="canAdd" type="primary" @click="openCreate">新建巡检任务</el-button>
    </div>

    <el-table :data="list" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="任务名称" min-width="150" />
      <el-table-column label="项目" min-width="130">
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="巡检人" min-width="100">
        <template #default="{ row }">{{ userName(row.assignee_id) }}</template>
      </el-table-column>
      <el-table-column label="时间窗" min-width="200">
        <template #default="{ row }">
          {{ row.start_time || "?" }} ~ {{ row.end_time || "?" }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="打卡" width="90">
        <template #default="{ row }">
          <span :class="{ danger: row.abnormal_count > 0 }">
            {{ row.checkin_count }}/{{ row.required_checkins }}
            <template v-if="row.abnormal_count > 0">（异{{ row.abnormal_count }}）</template>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button v-if="canEdit" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-for="a in transitionActions(row.status)"
            :key="a"
            link
            :type="a === 'cancel' ? 'danger' : 'success'"
            @click="doTransition(row, a)"
          >
            {{ a === "start" ? "开始" : a === "finish" ? "完成" : "取消" }}
          </el-button>
          <el-button v-if="canDelete" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无巡检任务</template>
    </el-table>

    <div class="pager">
      <el-pagination
        layout="prev, pager, next, total"
        :total="total"
        :page-size="size"
        :current-page="page"
        @current-change="pageChange"
      />
    </div>

    <!-- 创建/编辑 -->
    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新建巡检任务' : '编辑巡检任务'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="所属项目">
          <el-select v-model="form.project_id" placeholder="选择项目" clearable style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务名称" required>
          <el-input v-model="form.name" placeholder="请输入任务名称" />
        </el-form-item>
        <el-form-item label="巡检人">
          <el-select v-model="form.assignee_id" placeholder="选择用户" clearable style="width: 100%">
            <el-option
              v-for="u in users"
              :key="u.id"
              :label="`${u.nickname || u.username}（${u.username}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="任务内容">
          <el-input v-model="form.content" type="textarea" :rows="2" placeholder="巡检内容/要点（可选）" />
        </el-form-item>
        <el-form-item label="时间窗">
          <div class="time-range">
            <el-date-picker v-model="form.start_time" type="datetime" placeholder="开始" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            <span class="sep">~</span>
            <el-date-picker v-model="form.end_time" type="datetime" placeholder="结束" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
          </div>
        </el-form-item>
        <el-form-item label="要求打卡">
          <el-input-number v-model="form.required_checkins" :min="1" :max="100" />
          <span class="unit">次</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交</el-button>
      </template>
    </el-dialog>

    <!-- 详情 + 打卡 -->
    <el-dialog v-model="detailVisible" title="巡检任务详情" width="720px">
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务名称">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detail.status)" size="small">{{ detail.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="所属项目">{{ projectName(detail.project_id) }}</el-descriptions-item>
          <el-descriptions-item label="巡检人">{{ userName(detail.assignee_id) }}</el-descriptions-item>
          <el-descriptions-item label="时间窗" :span="2">
            {{ detail.start_time || "?" }} ~ {{ detail.end_time || "?" }}
          </el-descriptions-item>
          <el-descriptions-item label="内容" :span="2">{{ detail.content || "-" }}</el-descriptions-item>
          <el-descriptions-item label="打卡进度">
            {{ detail.checkin_count }}/{{ detail.required_checkins }}
          </el-descriptions-item>
          <el-descriptions-item label="异常数">{{ detail.abnormal_count }}</el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">打卡</el-divider>
        <el-form :inline="true" v-if="canCheckin && detail.status !== '已完成' && detail.status !== '已取消'">
          <el-form-item label="结果">
            <el-select v-model="checkinForm.result" style="width: 110px">
              <el-option label="正常" value="正常" />
              <el-option label="异常" value="异常" />
            </el-select>
          </el-form-item>
          <el-form-item label="经度"><el-input v-model.number="checkinForm.lng" placeholder="可选" style="width: 110px" /></el-form-item>
          <el-form-item label="纬度"><el-input v-model.number="checkinForm.lat" placeholder="可选" style="width: 110px" /></el-form-item>
          <el-form-item label="备注"><el-input v-model="checkinForm.note" placeholder="可选" style="width: 140px" /></el-form-item>
          <el-form-item><el-button type="primary" @click="submitCheckin">提交打卡</el-button></el-form-item>
        </el-form>
        <el-empty v-else description="当前状态不可打卡" :image-size="60" />

        <el-divider content-position="left">打卡记录</el-divider>
        <el-table :data="detail.records" border size="small" style="width: 100%">
          <el-table-column prop="checkin_by_name" label="打卡人" width="110" />
          <el-table-column prop="checkin_at" label="时间" min-width="150" />
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="row.result === '异常' ? 'danger' : 'success'" size="small">{{ row.result }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="120" />
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button
                v-if="row.result === '异常' && !row.hazard_id && canEdit"
                link
                type="warning"
                @click="toHazard(row.id)"
              >
                转隐患
              </el-button>
              <span v-else-if="row.hazard_id" style="color: #909399; font-size: 12px">已转隐患</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin: 12px 0; }
.filters { flex-wrap: wrap; }
.stat-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.stat-card { text-align: center; }
.stat-num { font-size: 26px; font-weight: 700; color: #303133; }
.stat-num.warning { color: #e6a23c; }
.stat-num.info { color: #909399; }
.stat-num.danger { color: #f56c6c; }
.stat-label { font-size: 13px; color: #909399; margin-top: 4px; }
.pager { margin-top: 12px; }
.danger { color: #f56c6c; font-weight: 600; }
.unit { margin-left: 8px; color: #909399; font-size: 12px; }
.sep { color: #909399; }
.time-range { display: flex; align-items: center; gap: 8px; width: 100%; }
</style>
