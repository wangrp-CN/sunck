<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { fetchProjects } from "@/api/project";
import { listUsers } from "@/api/user";
import TablePager from "@/components/TablePager.vue";
import {
  createDutyRoster,
  deleteDutyRoster,
  getDutyMeta,
  getOnDuty,
  listDutyRosters,
  updateDutyRoster,
  type DutyRoster,
  type OnDutyResult,
} from "@/api/duty";

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission("duty:manage"));

const items = ref<DutyRoster[]>([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const size = ref(20);

const projects = ref<{ id: number; name: string }[]>([]);
const users = ref<{ id: number; name: string }[]>([]);
const shifts = ref<string[]>(["白班", "夜班", "早班", "中班", "晚班"]);

const filterProject = ref<number | null>(null);
const filterActive = ref(false);

// 当前值班（按筛选项目的实时兜底人）横幅
const onDuty = ref<OnDutyResult | null>(null);

async function loadProjects() {
  try {
    const r = await fetchProjects({ page: 1, size: 200 });
    projects.value = (r.items || []).map((p: any) => ({ id: p.id, name: p.name }));
  } catch {
    projects.value = [];
  }
}

async function loadUsers() {
  try {
    const r = await listUsers({ page: 1, size: 200 });
    users.value = (r.items || []).map((u: any) => ({ id: u.id, name: u.nickname || u.username }));
  } catch {
    users.value = [];
  }
}

async function refreshOnDuty() {
  if (!filterProject.value) {
    onDuty.value = null;
    return;
  }
  try {
    onDuty.value = await getOnDuty(filterProject.value);
  } catch {
    onDuty.value = null;
  }
}

async function load() {
  loading.value = true;
  try {
    const res = await listDutyRosters({
      project_id: filterProject.value || undefined,
      active: filterActive.value || undefined,
      page: page.value,
      size: size.value,
    });
    items.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载排班失败");
  } finally {
    loading.value = false;
  }
}

watch(filterProject, () => {
  page.value = 1;
  refreshOnDuty();
  load();
});
watch(filterActive, () => {
  page.value = 1;
  load();
});

// ---- 新增 / 编辑 ----
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const form = ref({
  project_id: null as number | null,
  user_id: null as number | null,
  shift: "白班",
  duty_role: "" as string,
  start_time: "" as string,
  end_time: "" as string,
  note: "" as string,
});

function resetForm() {
  form.value = {
    project_id: filterProject.value || null,
    user_id: null,
    shift: "白班",
    duty_role: "",
    start_time: "",
    end_time: "",
    note: "",
  };
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: DutyRoster) {
  editingId.value = row.id;
  form.value = {
    project_id: row.project_id,
    user_id: row.user_id,
    shift: row.shift,
    duty_role: row.duty_role || "",
    start_time: row.start_time,
    end_time: row.end_time,
    note: row.note || "",
  };
  dialogVisible.value = true;
}

async function submitForm() {
  if (!form.value.project_id) {
    ElMessage.warning("请选择归属项目");
    return;
  }
  if (!form.value.user_id) {
    ElMessage.warning("请选择值班人");
    return;
  }
  if (!form.value.start_time || !form.value.end_time) {
    ElMessage.warning("请选择值班起止时间");
    return;
  }
  if (form.value.end_time <= form.value.start_time) {
    ElMessage.warning("结束时间须晚于开始时间");
    return;
  }
  submitting.value = true;
  try {
    const payload = {
      project_id: form.value.project_id,
      user_id: form.value.user_id,
      shift: form.value.shift,
      duty_role: form.value.duty_role || null,
      start_time: form.value.start_time,
      end_time: form.value.end_time,
      note: form.value.note || null,
    };
    if (editingId.value) {
      await updateDutyRoster(editingId.value, payload);
      ElMessage.success("排班已更新");
    } else {
      await createDutyRoster(payload);
      ElMessage.success("排班已新增");
    }
    dialogVisible.value = false;
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    submitting.value = false;
  }
}

async function removeRow(row: DutyRoster) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.project_name || "项目"} · ${row.user_name || "未知"} · ${row.shift}」排班？`, "删除确认", {
      type: "warning",
    });
  } catch {
    return; // 取消
  }
  try {
    await deleteDutyRoster(row.id);
    ElMessage.success("已删除");
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

// YYYY-MM-DDTHH:mm:ss → MM-DD HH:mm
function fmt(ts: string): string {
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (m) return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
  return ts;
}

onMounted(async () => {
  await Promise.all([loadProjects(), loadUsers()]);
  try {
    const meta = await getDutyMeta();
    shifts.value = meta.shifts || shifts.value;
  } catch {
    /* 用默认班次 */
  }
  load();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <span class="title">值班排班</span>
      <el-button v-if="canManage" type="primary" @click="openCreate">新增排班</el-button>
    </div>

    <!-- 当前值班横幅：派单自动兜底来源的可视化 -->
    <el-alert
      v-if="filterProject && onDuty"
      class="onduty"
      :title="`当前值班：${onDuty.user_name || '无人值班'}`"
      :description="onDuty.user_name ? '新建派单未指定处理人时，将自动派给该值班人。' : '该项目当前无在班人员，派单将保持「待派」状态。'"
      :type="onDuty.user_name ? 'success' : 'warning'"
      :closable="false"
      show-icon
    />
    <el-alert
      v-else-if="filterProject && !onDuty"
      class="onduty"
      title="查询当前值班失败"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="filters">
      <el-select v-model="filterProject as any" clearable placeholder="按项目筛选" style="width: 200px">
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-switch
        v-model="filterActive"
        active-text="仅显示在班"
        inline-prompt
      />
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="items" v-loading="loading" border stripe style="width: 100%">
      <el-table-column label="序号" width="64" align="center">
        <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
      </el-table-column>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="project_name" label="项目" min-width="120" />
      <el-table-column prop="user_name" label="值班人" width="120" />
      <el-table-column prop="shift" label="班次" width="90" />
      <el-table-column prop="duty_role" label="职责" min-width="110">
        <template #default="{ row }">{{ row.duty_role || "—" }}</template>
      </el-table-column>
      <el-table-column label="开始" width="120">
        <template #default="{ row }">{{ fmt(row.start_time) }}</template>
      </el-table-column>
      <el-table-column label="结束" width="120">
        <template #default="{ row }">{{ fmt(row.end_time) }}</template>
      </el-table-column>
      <el-table-column label="在班" width="80" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_current" type="success" size="small">在班</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="note" label="备注" min-width="140">
        <template #default="{ row }">{{ row.note || "—" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right" v-if="canManage">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无排班</template>
    </el-table>

    <TablePager v-model:page="page" v-model:size="size" :total="total" @change="load" />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑排班' : '新增排班'"
      width="520px"
      @closed="dialogVisible = false"
    >
      <el-form label-width="92px">
        <el-form-item label="归属项目">
          <el-select v-model="form.project_id as any" filterable placeholder="选择项目" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="值班人">
          <el-select v-model="form.user_id as any" filterable placeholder="选择值班人" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="班次">
          <el-select v-model="form.shift" style="width: 100%">
            <el-option v-for="s in shifts" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="职责">
          <el-input v-model="form.duty_role" placeholder="如：现场指挥 / 监控值守" />
        </el-form-item>
        <el-form-item label="开始时间">
          <el-date-picker
            v-model="form.start_time as any"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="开始时间"
            style="width: 100%" format="YYYY年MM月DD日 HH:mm"
          />
        </el-form-item>
        <el-form-item label="结束时间">
          <el-date-picker
            v-model="form.end_time as any"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="结束时间"
            style="width: 100%" format="YYYY年MM月DD日 HH:mm"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 15px; font-weight: 600; color: #303133; }
.onduty { margin-bottom: 12px; }
.filters { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.muted { color: #c0c4cc; font-size: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
</style>
