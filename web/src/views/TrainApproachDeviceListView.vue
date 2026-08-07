<script setup lang="ts">
/**
 * 列车接近报警设备列表（原型《列车接近报警设备列表》+《新增设备》弹窗）。
 *
 * 搜索区：项目名称（下拉，当前用户可见项目）、设备名称（左右模糊）、
 *         设备编号（精确）、设备状态（在线/不在线/低电量）+ 查询/重置/新增。
 * 列表区：按创建时间倒序，列 = 序号/项目名称/设备名称/设备编号/设备状态/创建时间/操作。
 * 弹窗：新增 / 编辑 / 查看 三态复用；删除二次确认「您确认删除当前设备？」。
 * 坐标：经纬度按系统约定入库 WGS-84（与设备/隐患一致）。
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
  batchDeleteTrainApproachDevices,
  createTrainApproachDevice,
  deleteTrainApproachDevice,
  fetchTrainApproachDevices,
  updateTrainApproachDevice,
} from "@/api/trainApproachDevice";
import { fetchProjects } from "@/api/project";
import TablePager from "@/components/TablePager.vue";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import { TRAIN_APPROACH_DEVICE_DIRECTIONS, TRAIN_APPROACH_DEVICE_STATUSES } from "@/types";
import type {
  Project,
  TrainApproachDevice,
  TrainApproachDeviceCreate,
  TrainApproachDeviceListParams,
  TrainApproachDeviceUpdate,
} from "@/types";

const auth = useAuthStore();
const route = useRoute();

// 权限门控（后端仍会二次校验）；hasPermission 兼容超管（permission_codes 可能为空）
const canAdd = computed(() => auth.hasPermission("train_approach_device:add"));
const canEdit = computed(() => auth.hasPermission("train_approach_device:edit"));
const canDelete = computed(() => auth.hasPermission("train_approach_device:delete"));

const loading = ref(false);
const tableData = ref<TrainApproachDevice[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);

// 项目下拉（当前用户数据范围内的项目，后端已按 DataScope 过滤）
const projects = ref<Project[]>([]);

/** 设备状态标签色：在线=绿 / 不在线=灰 / 低电量=橙，与其它设备列表一致 */
const statusTagType: Record<string, "" | "success" | "warning" | "info"> = {
  在线: "success",
  不在线: "info",
  低电量: "warning",
};

// ---- 查询条件（对齐原型搜索区）----
const query = reactive({
  project_id: null as number | null,
  name: "",
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

function projectName(row: TrainApproachDevice): string {
  if (row.project_name) return row.project_name;
  if (row.project_id == null) return "—";
  const hit = projects.value.find((p) => p.id === row.project_id);
  return hit ? hit.name : `ID:${row.project_id}`;
}

function buildParams(): TrainApproachDeviceListParams {
  return {
    project_id: query.project_id ?? undefined,
    name: query.name.trim() || undefined,
    device_no: query.device_no.trim() || undefined,
    status: query.status ?? undefined,
    page: page.value,
    size: size.value,
  };
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchTrainApproachDevices(buildParams());
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
    ? "新增列车接近报警设备"
    : dialogMode.value === "edit"
      ? "编辑列车接近报警设备"
      : "查看列车接近报警设备",
);

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  name: "",
  device_no: "",
  sn: "",
  direction: "",
  longitude: undefined as number | undefined,
  latitude: undefined as number | undefined,
  status: "在线" as string,
});

const form = reactive(emptyForm());

const rules: FormRules = {
  project_id: [{ required: true, message: "请选择项目名称", trigger: "change" }],
  name: [{ required: true, message: "请输入设备名称", trigger: "blur" }],
  device_no: [{ required: true, message: "请输入设备编号", trigger: "blur" }],
  sn: [{ required: true, message: "请输入设备SN码", trigger: "blur" }],
  status: [{ required: true, message: "请选择设备状态", trigger: "change" }],
  direction: [{ required: true, message: "请选择设备方位", trigger: "change" }],
  longitude: [{ required: true, message: "请输入经度", trigger: "change" }],
  latitude: [{ required: true, message: "请输入纬度", trigger: "change" }],
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

function fillForm(row: TrainApproachDevice) {
  editingId.value = row.id;
  Object.assign(form, emptyForm(), {
    project_id: row.project_id ?? undefined,
    name: row.name,
    device_no: row.device_no,
    sn: row.sn ?? "",
    direction: row.direction ?? "",
    longitude: row.longitude ?? undefined,
    latitude: row.latitude ?? undefined,
    status: row.status,
  });
  dialogVisible.value = true;
}

function openEdit(row: TrainApproachDevice) {
  dialogMode.value = "edit";
  fillForm(row);
}

function openView(row: TrainApproachDevice) {
  dialogMode.value = "view";
  fillForm(row);
}

function buildData(): TrainApproachDeviceCreate {
  return {
    project_id: form.project_id as number,
    name: form.name.trim(),
    device_no: form.device_no.trim(),
    sn: form.sn ? form.sn.trim() || null : null,
    direction: form.direction ? form.direction.trim() || null : null,
    longitude: form.longitude ?? null,
    latitude: form.latitude ?? null,
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
        await createTrainApproachDevice(payload);
        ElMessage.success("设备创建成功");
      } else {
        await updateTrainApproachDevice(
          editingId.value as number,
          payload as TrainApproachDeviceUpdate,
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

async function handleDelete(row: TrainApproachDevice) {
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
    await deleteTrainApproachDevice(row.id);
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
  deleteApi: batchDeleteTrainApproachDevices,
  reload: () => loadData(),
  label: "列车接近报警设备",
});
</script>

<template>
  <div class="train-approach-device-page">
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
      <el-input
        v-model="query.device_no"
        placeholder="设备编号"
        clearable
        class="w-160"
        @keyup.enter="handleSearch"
      />
      <el-select v-model="query.status" placeholder="设备状态" clearable class="w-140">
        <el-option
          v-for="s in TRAIN_APPROACH_DEVICE_STATUSES"
          :key="s"
          :label="s"
          :value="s"
        />
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
      <el-table-column prop="name" label="设备名称" min-width="180" show-overflow-tooltip />
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
      <template #empty>
        <el-empty description="暂无列车接近报警设备" :image-size="80" />
      </template>
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
            <el-form-item label="设备编号" prop="device_no">
              <el-input v-model="form.device_no" placeholder="唯一编号" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备SN码" prop="sn">
              <el-input v-model="form.sn" placeholder="请输入设备SN码" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备方位" prop="direction">
              <el-select
                v-model="form.direction"
                placeholder="请选择设备方位"
                class="full"
              >
                <el-option
                  v-for="d in TRAIN_APPROACH_DEVICE_DIRECTIONS"
                  :key="d"
                  :label="d"
                  :value="d"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备状态" prop="status">
              <el-select v-model="form.status" class="full">
                <el-option
                  v-for="s in TRAIN_APPROACH_DEVICE_STATUSES"
                  :key="s"
                  :label="s"
                  :value="s"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="经度" prop="longitude">
              <el-input-number
                v-model="form.longitude"
                :precision="6"
                :controls="false"
                :min="-180"
                :max="180"
                placeholder="WGS-84 经度"
                class="full"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="纬度" prop="latitude">
              <el-input-number
                v-model="form.latitude"
                :precision="6"
                :controls="false"
                :min="-90"
                :max="90"
                placeholder="WGS-84 纬度"
                class="full"
              />
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
.train-approach-device-page {
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
