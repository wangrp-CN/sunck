<script setup lang="ts">
/**
 * 大型机械列表（原型《大型机械列表》）。
 *
 * 搜索区：项目名称（下拉，当前用户可见项目）、大机编号（精确）、
 *         大机类型（挖掘机/打桩机/吊机 下拉）+ 查询/重置/新增。
 * 列表区：按创建时间倒序，列 = 序号/项目名称/大机编号/大机类型/规格及型号/大机设备说明/创建时间/操作。
 * 弹窗（对齐《新增大机》《编辑大机》《查看大机》）：单列全宽；字段顺序
 *   项目名称(选填) → 大机编号(必填) → 规格与型号(选填) → 设备类型(必填) → 大机设备说明(必填)；查看态只读。
 *
 * 复用既有 Machine 实体（表 machine）与 /v1/machines 接口，权限码 machine:*。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  batchDeleteMachines,
  createMachine,
  deleteMachine,
  fetchMachines,
  updateMachine,
} from "@/api/machine";
import { fetchProjects } from "@/api/project";
import TablePager from "@/components/TablePager.vue";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import { MACHINE_TYPES } from "@/types";
import type {
  Machine,
  MachineCreate,
  MachineListParams,
  MachineUpdate,
  Project,
} from "@/types";

const auth = useAuthStore();
const route = useRoute();

// 权限门控（后端仍会二次校验）；hasPermission 兼容超管（permission_codes 可能为空）
const canAdd = computed(() => auth.hasPermission("machine:add"));
const canEdit = computed(() => auth.hasPermission("machine:edit"));
const canDelete = computed(() => auth.hasPermission("machine:delete"));

const loading = ref(false);
const tableData = ref<Machine[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

// 项目下拉（当前用户数据范围内的项目，后端已按 DataScope 过滤）
const projects = ref<Project[]>([]);
const projectMap = ref<Map<number, string>>(new Map());

/** 大机类型下拉：固定三选项；编辑历史自由文本值时追加为可选项以保留原值 */
const typeOptions = computed<string[]>(() => {
  const opts = [...MACHINE_TYPES];
  if (form.machine_type && !MACHINE_TYPES.includes(form.machine_type)) {
    opts.push(form.machine_type);
  }
  return opts;
});

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
    projects.value = all;
    const map = new Map<number, string>();
    all.forEach((pr: Project) => map.set(pr.id, pr.name));
    projectMap.value = map;
  } catch {
    // 项目加载失败不阻断列表
  }
}

function projectName(row: Machine): string {
  if (row.project_name) return row.project_name;
  if (row.project_id == null) return "—";
  const hit = projectMap.value.get(row.project_id);
  return hit ? hit : `ID:${row.project_id}`;
}

// ---- 查询条件（对齐原型搜索区）----
const query = reactive({
  project_id: null as number | null,
  machine_no: "",
  machine_type: null as string | null,
});

function buildParams(): MachineListParams {
  return {
    project_id: query.project_id ?? undefined,
    machine_no: query.machine_no.trim() || undefined,
    machine_type: query.machine_type ?? undefined,
    page: page.value,
    size: size.value,
  };
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchMachines(buildParams());
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
  query.project_id = null;
  query.machine_no = "";
  query.machine_type = null;
  page.value = 1;
  loadData();
}

// ---- 新增 / 编辑 / 查看 弹窗 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit" | "view">("create");
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();

const isView = computed(() => dialogMode.value === "view");
const dialogTitle = computed(() =>
  dialogMode.value === "create"
    ? "新增大机"
    : dialogMode.value === "edit"
      ? "编辑大机"
      : "查看大机",
);

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  machine_no: "",
  machine_type: "" as string,
  spec_model: "",
  description: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  machine_no: [{ required: true, message: "请输入大机编号", trigger: "blur" }],
  machine_type: [{ required: true, message: "请选择设备类型", trigger: "change" }],
  description: [{ required: true, message: "请输入大机设备说明", trigger: "blur" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm(), {
    // 原型：默认为列表页当前筛选项目
    project_id: query.project_id ?? undefined,
  });
  dialogVisible.value = true;
}

function fillForm(row: Machine) {
  editingId.value = row.id;
  Object.assign(form, emptyForm(), {
    project_id: row.project_id ?? undefined,
    machine_no: row.machine_no,
    machine_type: row.machine_type ?? "",
    spec_model: row.spec_model ?? "",
    description: row.description ?? "",
  });
  dialogVisible.value = true;
}

function openEdit(row: Machine) {
  dialogMode.value = "edit";
  fillForm(row);
}

function openView(row: Machine) {
  dialogMode.value = "view";
  fillForm(row);
}

function buildData(): MachineCreate {
  return {
    project_id: form.project_id as number,
    machine_no: form.machine_no.trim(),
    machine_type: form.machine_type ? form.machine_type.trim() || null : null,
    spec_model: form.spec_model ? form.spec_model.trim() || null : null,
    description: form.description ? form.description.trim() || null : null,
  };
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const payload = buildData();
      if (dialogMode.value === "create") {
        await createMachine(payload);
        ElMessage.success("大机创建成功");
      } else {
        await updateMachine(
          editingId.value as number,
          payload as MachineUpdate,
        );
        ElMessage.success("大机更新成功");
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
    await ElMessageBox.confirm("您确认删除当前大机？", "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await deleteMachine(row.id);
    ElMessage.success("大机已删除");
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
  // 支持从大屏/项目详情页带 ?project_id= 跳入并预选项目
  const pid = Number(route.query.project_id);
  if (Number.isFinite(pid) && pid > 0) query.project_id = pid;
  loadProjects();
  loadData();
});

// 暴露内部状态，便于单测确定性驱动
defineExpose({
  query,
  form,
  tableData,
  rules,
  typeOptions,
  buildData,
  handleSearch,
  handleReset,
  openCreate,
  openEdit,
  openView,
  handleDelete,
  handleSubmit,
});

// ---- 批量选择 / 批量删除（统一交互，见 useBatchSelection + BatchActions）----
const {
  tableRef,
  selectedRows,
  batchDeleting,
  onSelectionChange,
  clearSelection,
  onBatchDelete,
} = useBatchSelection({
  deleteApi: batchDeleteMachines,
  reload: () => loadData(),
  label: "大机",
});
</script>

<template>
  <div class="large-machine-page">
    <!-- 查询区 -->
    <div class="toolbar">
      <el-select
        v-model="query.project_id"
        placeholder="项目名称"
        clearable
        filterable
        class="w-220"
      >
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-input
        v-model="query.machine_no"
        placeholder="大机编号"
        clearable
        class="w-180"
        @keyup.enter="handleSearch"
      />
      <el-select v-model="query.machine_type" placeholder="大机类型" clearable class="w-180">
        <el-option v-for="t in MACHINE_TYPES" :key="t" :label="t" :value="t" />
      </el-select>
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增</el-button>
    </div>

    <!-- 列表区（按创建时间倒序） -->
    <BatchActions
      v-if="canDelete"
      :selected="selectedRows.length"
      :loading="batchDeleting"
      @batch-delete="onBatchDelete"
      @clear="clearSelection"
    />
    <el-table
      ref="tableRef"
      v-loading="loading"
      :data="tableData"
      border
      stripe
      class="table"
      row-key="id"
      @selection-change="onSelectionChange"
    >
      <el-table-column
        v-if="canDelete"
        type="selection"
        width="48"
        :reserve-selection="true"
        fixed="left"
      />
      <el-table-column label="序号" width="64" align="center" fixed="left">
        <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
      </el-table-column>
      <el-table-column label="项目名称" min-width="180" show-overflow-tooltip fixed="left">
        <template #default="{ row }">{{ projectName(row) }}</template>
      </el-table-column>
      <el-table-column prop="machine_no" label="大机编号" width="140" show-overflow-tooltip />
      <el-table-column label="大机类型" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="row.machine_type" type="info" effect="light">{{ row.machine_type }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="规格及型号" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.spec_model || '—' }}</template>
      </el-table-column>
      <el-table-column label="大机设备说明" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.description || '—' }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="info" @click="openView(row)">查看</el-button>
          <el-button v-if="canEdit" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canDelete" link type="danger" @click="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pager">
      <TablePager
        v-model:page="page"
        v-model:size="size"
        :total="total"
        :selected="selectedRows.length"
        @change="loadData"
      />
    </div>

    <!-- 新增 / 编辑 / 查看 弹窗（对齐原型《新增大机》《编辑大机》《查看大机》） -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="96px"
        :disabled="isView"
      >
        <el-form-item label="项目名称" prop="project_id">
          <el-select
            v-model="form.project_id"
            placeholder="请选择项目"
            filterable
            clearable
            class="full"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="大机编号" prop="machine_no">
          <el-input v-model="form.machine_no" placeholder="请输入大机编号" />
        </el-form-item>
        <el-form-item label="规格与型号">
          <el-input v-model="form.spec_model" placeholder="请输入规格与型号（选填）" />
        </el-form-item>
        <el-form-item label="设备类型" prop="machine_type">
          <el-select v-model="form.machine_type" placeholder="请选择设备类型" clearable class="full">
            <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="大机设备说明" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="请输入大机设备说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ isView ? "关闭" : "取消" }}</el-button>
        <el-button v-if="!isView" type="primary" :loading="submitting" @click="handleSubmit">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.large-machine-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.w-180 {
  width: 180px;
}
.w-220 {
  width: 220px;
}
.full {
  width: 100%;
}
.table {
  width: 100%;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
