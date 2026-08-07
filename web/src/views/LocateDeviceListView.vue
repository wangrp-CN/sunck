<script setup lang="ts">
/**
 * 人机定位设备列表（原型《人机定位设备列表》）。
 *
 * 搜索区：项目名称（下拉，当前用户可见项目）、设备名称（左右模糊）、
 *         设备类型（人员手持机/工牌/手环定位设备、大机机械定位设备）、
 *         设备编号（精确）、设备状态（在线/不在线/低电量）+ 查询/重置/新增。
 * 列表区：按创建时间倒序，列 = 序号/项目名称/设备名称/设备类型/设备编号/设备状态/创建时间/操作。
 * 弹窗：新增 / 编辑 / 查看 三态复用；删除二次确认「您确认删除当前设备？」。
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
  batchDeleteLocateDevices,
  createLocateDevice,
  deleteLocateDevice,
  fetchLocateDevices,
  updateLocateDevice,
} from "@/api/locateDevice";
import { fetchProjects } from "@/api/project";
import TablePager from "@/components/TablePager.vue";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import { DEVICE_FUNCTIONS, LOCATE_DEVICE_STATUSES, LOCATE_DEVICE_TYPES } from "@/types";
import type {
  DeviceFunction,
  LocateDevice,
  LocateDeviceCreate,
  LocateDeviceListParams,
  LocateDeviceUpdate,
  Project,
} from "@/types";

const auth = useAuthStore();
const route = useRoute();

// 权限门控（后端仍会二次校验）；hasPermission 兼容超管（permission_codes 可能为空）
const canAdd = computed(() => auth.hasPermission("locate_device:add"));
const canEdit = computed(() => auth.hasPermission("locate_device:edit"));
const canDelete = computed(() => auth.hasPermission("locate_device:delete"));

const loading = ref(false);
const tableData = ref<LocateDevice[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);

// 项目下拉（当前用户数据范围内的项目，后端已按 DataScope 过滤）
const projects = ref<Project[]>([]);

/** 设备状态标签色：在线=绿 / 不在线=灰 / 低电量=橙，与通用设备状态配色语义一致 */
const statusTagType: Record<string, "" | "success" | "warning" | "info"> = {
  在线: "success",
  不在线: "info",
  低电量: "warning",
};

/** 设备功能下拉：固定三选项；编辑历史自由文本值时追加为可选项以保留原值 */
const functionOptions = computed<string[]>(() => {
  const opts = [...DEVICE_FUNCTIONS] as string[];
  if (form.function && !DEVICE_FUNCTIONS.includes(form.function as DeviceFunction)) {
    opts.push(form.function);
  }
  return opts;
});

// ---- 查询条件（对齐原型搜索区）----
const query = reactive({
  project_id: null as number | null,
  name: "",
  device_type: null as string | null,
  device_no: "",
  status: null as string | null,
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
  } catch {
    // 项目加载失败不阻断列表
  }
}

function projectName(row: LocateDevice): string {
  if (row.project_name) return row.project_name;
  if (row.project_id == null) return "—";
  const hit = projects.value.find((p) => p.id === row.project_id);
  return hit ? hit.name : `ID:${row.project_id}`;
}

function buildParams(): LocateDeviceListParams {
  return {
    project_id: query.project_id ?? undefined,
    name: query.name.trim() || undefined,
    device_type: query.device_type ?? undefined,
    device_no: query.device_no.trim() || undefined,
    status: query.status ?? undefined,
    page: page.value,
    size: size.value,
  };
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchLocateDevices(buildParams());
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
  query.name = "";
  query.device_type = null;
  query.device_no = "";
  query.status = null;
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
    ? "新增人机定位设备"
    : dialogMode.value === "edit"
      ? "编辑人机定位设备"
      : "查看人机定位设备",
);

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  name: "",
  device_no: "",
  device_type: LOCATE_DEVICE_TYPES[0] as string,
  function: "",
  sn: "",
  status: "在线" as string,
});

const form = reactive(emptyForm());

const rules: FormRules = {
  project_id: [{ required: true, message: "请选择项目名称", trigger: "change" }],
  name: [{ required: true, message: "请输入设备名称", trigger: "blur" }],
  device_type: [{ required: true, message: "请选择设备类型", trigger: "change" }],
  device_no: [{ required: true, message: "请输入设备编号", trigger: "blur" }],
  status: [{ required: true, message: "请选择设备状态", trigger: "change" }],
  sn: [{ required: true, message: "请输入设备SN码", trigger: "blur" }],
  function: [{ required: true, message: "请选择设备功能", trigger: "change" }],
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

function fillForm(row: LocateDevice) {
  editingId.value = row.id;
  Object.assign(form, emptyForm(), {
    project_id: row.project_id ?? undefined,
    name: row.name,
    device_no: row.device_no,
    device_type: row.device_type ?? LOCATE_DEVICE_TYPES[0],
    function: row.function ?? "",
    sn: row.sn ?? "",
    status: row.status,
  });
  dialogVisible.value = true;
}

function openEdit(row: LocateDevice) {
  dialogMode.value = "edit";
  fillForm(row);
}

function openView(row: LocateDevice) {
  dialogMode.value = "view";
  fillForm(row);
}

function buildData(): LocateDeviceCreate {
  return {
    project_id: form.project_id as number,
    name: form.name.trim(),
    device_no: form.device_no.trim(),
    device_type: form.device_type || null,
    function: form.function ? form.function.trim() || null : null,
    sn: form.sn ? form.sn.trim() || null : null,
    status: form.status,
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
        await createLocateDevice(payload);
        ElMessage.success("设备创建成功");
      } else {
        await updateLocateDevice(
          editingId.value as number,
          payload as LocateDeviceUpdate,
        );
        ElMessage.success("设备更新成功");
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

async function handleDelete(row: LocateDevice) {
  try {
    await ElMessageBox.confirm("您确认删除当前设备？", "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await deleteLocateDevice(row.id);
    ElMessage.success("设备已删除");
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
  statusTagType,
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
  deleteApi: batchDeleteLocateDevices,
  reload: () => loadData(),
  label: "人机定位设备",
});
</script>

<template>
  <div class="locate-device-page">
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
        v-model="query.name"
        placeholder="设备名称"
        clearable
        class="w-180"
        @keyup.enter="handleSearch"
      />
      <el-select v-model="query.device_type" placeholder="设备类型" clearable class="w-200">
        <el-option v-for="t in LOCATE_DEVICE_TYPES" :key="t" :label="t" :value="t" />
      </el-select>
      <el-input
        v-model="query.device_no"
        placeholder="设备编号"
        clearable
        class="w-160"
        @keyup.enter="handleSearch"
      />
      <el-select v-model="query.status" placeholder="设备状态" clearable class="w-140">
        <el-option v-for="s in LOCATE_DEVICE_STATUSES" :key="s" :label="s" :value="s" />
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
      <el-table-column prop="name" label="设备名称" min-width="160" show-overflow-tooltip />
      <el-table-column label="设备类型" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="row.device_type" type="info" effect="light">{{ row.device_type }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="device_no" label="设备编号" width="140" show-overflow-tooltip />
      <el-table-column label="设备状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status] || ''" effect="light">
            {{ row.status }}
          </el-tag>
        </template>
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

    <!-- 新增 / 编辑 / 查看 弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="640px"
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
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="项目名称" prop="project_id">
              <el-select
                v-model="form.project_id"
                placeholder="请选择项目"
                filterable
                class="full"
              >
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备名称" prop="name">
              <el-input v-model="form.name" placeholder="请输入设备名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备类型" prop="device_type">
              <el-select v-model="form.device_type" class="full">
                <el-option v-for="t in LOCATE_DEVICE_TYPES" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备编号" prop="device_no">
              <el-input v-model="form.device_no" placeholder="唯一编号" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备状态" prop="status">
              <el-select v-model="form.status" class="full">
                <el-option v-for="s in LOCATE_DEVICE_STATUSES" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备SN码" prop="sn">
              <el-input v-model="form.sn" placeholder="请输入设备SN码" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="设备功能" prop="function">
              <el-select v-model="form.function" placeholder="请选择设备功能" class="full">
                <el-option v-for="f in functionOptions" :key="f" :label="f" :value="f" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
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
.locate-device-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.w-140 {
  width: 140px;
}
.w-160 {
  width: 160px;
}
.w-180 {
  width: 180px;
}
.w-200 {
  width: 200px;
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
