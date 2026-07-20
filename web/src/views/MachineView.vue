<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createMachine,
  deleteMachine,
  fetchMachines,
  updateMachine,
} from "@/api/machine";
import { fetchProjects } from "@/api/project";
import type { Machine, MachineCreate, MachineUpdate, Project } from "@/types";
import AttachmentManager from "@/components/AttachmentManager.vue";

const auth = useAuthStore();

const canAdd = computed(() => auth.user?.permission_codes.includes("machine:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("machine:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("machine:delete") ?? false);

const loading = ref(false);
const keyword = ref("");
const tableData = ref<Machine[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

const projectMap = ref<Map<number, string>>(new Map());

function projectName(id: number | null): string {
  if (id == null) return "—";
  return projectMap.value.get(id) ?? `ID:${id}`;
}

async function loadProjects() {
  try {
    const all: Project[] = [];
    let p = 1;
    while (p <= 10) {
      const pd = await fetchProjects({ page: p, size: 200 });
      all.push(...pd.items);
      if (all.length >= pd.total) break;
      p++;
    }
    const map = new Map<number, string>();
    all.forEach((pr: Project) => map.set(pr.id, pr.name));
    projectMap.value = map;
  } catch {
    // 不影响列表
  }
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchMachines({
      keyword: keyword.value || undefined,
      page: page.value,
      size: size.value,
    });
    tableData.value = pageData.items;
    total.value = pageData.total;
  } catch {
    // 拦截器统一提示
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.value = 1;
  loadData();
}
function handleReset() {
  keyword.value = "";
  page.value = 1;
  loadData();
}
function handlePageChange(p: number) {
  page.value = p;
  loadData();
}

// ---- 新增/编辑弹窗 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  machine_no: "",
  machine_type: "",
  spec_model: "",
  description: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  project_id: [{ required: true, message: "请选择归属项目", trigger: "change" }],
  machine_no: [{ required: true, message: "请输入大机编号", trigger: "blur" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm());
  dialogVisible.value = true;
}

async function openEdit(row: Machine) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    project_id: row.project_id ?? undefined,
    machine_no: row.machine_no,
    machine_type: row.machine_type ?? "",
    spec_model: row.spec_model ?? "",
    description: row.description ?? "",
  });
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const payload: MachineCreate | MachineUpdate = {
        project_id: form.project_id as number,
        machine_no: form.machine_no,
        machine_type: form.machine_type ? form.machine_type : null,
        spec_model: form.spec_model ? form.spec_model : null,
        description: form.description ? form.description : null,
      };
      if (dialogMode.value === "create") {
        await createMachine(payload as MachineCreate);
        ElMessage.success("机械创建成功");
      } else {
        await updateMachine(editingId.value as number, payload as MachineUpdate);
        ElMessage.success("机械更新成功");
      }
      dialogVisible.value = false;
      loadData();
    } catch {
      // 拦截器统一提示
    } finally {
      submitting.value = false;
    }
  });
}

async function handleDelete(row: Machine) {
  try {
    await ElMessageBox.confirm(
      `确定删除机械「${row.machine_no}」吗？该操作将软删机械。`,
      "删除确认",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await deleteMachine(row.id);
    ElMessage.success("机械已删除");
    loadData();
  } catch {
    // 拦截器统一提示
  }
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      // 拦截器已处理
    }
  }
  loadProjects();
  loadData();
});
</script>

<template>
  <div class="machine-page">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按编号/类型搜索"
        clearable
        class="search-input"
        @keyup.enter="handleSearch"
        @clear="handleReset"
      />
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增机械</el-button>
    </div>

    <el-table v-loading="loading" :data="tableData" border stripe class="table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="machine_no" label="大机编号" width="140" />
      <el-table-column label="类型" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.machine_type || '—' }}</template>
      </el-table-column>
      <el-table-column label="规格型号" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.spec_model || '—' }}</template>
      </el-table-column>
      <el-table-column label="说明" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.description || '—' }}</template>
      </el-table-column>
      <el-table-column label="归属项目" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canDelete" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增机械' : '编辑机械'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="归属项目" prop="project_id">
          <el-select v-model="form.project_id" placeholder="请选择项目" class="full">
            <el-option
              v-for="[id, name] in projectMap"
              :key="id"
              :label="name"
              :value="id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="大机编号" prop="machine_no">
          <el-input v-model="form.machine_no" placeholder="大机编号" />
        </el-form-item>
        <el-form-item label="类型">
          <el-input v-model="form.machine_type" placeholder="大机类型（可选）" />
        </el-form-item>
        <el-form-item label="规格型号">
          <el-input v-model="form.spec_model" placeholder="规格及型号（可选）" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="大机设备说明（可选）" />
        </el-form-item>
      </el-form>
      <el-divider v-if="dialogMode === 'edit'" content-position="left">机械档案图 / 附件</el-divider>
      <AttachmentManager
        v-if="dialogMode === 'edit'"
        entity-type="machine"
        :entity-id="editingId"
      />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.machine-page { padding: 4px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.search-input { width: 240px; }
.full { width: 100%; }
.table { width: 100%; }
.pager { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
