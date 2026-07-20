<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createDevice,
  deleteDevice,
  fetchDevices,
  updateDevice,
} from "@/api/device";
import { fetchProjects } from "@/api/project";
import type {
  Device,
  DeviceCreate,
  DeviceType,
  DeviceUpdate,
  Project,
} from "@/types";
import AttachmentManager from "@/components/AttachmentManager.vue";

const auth = useAuthStore();

const canAdd = computed(() => auth.user?.permission_codes.includes("device:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("device:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("device:delete") ?? false);

const loading = ref(false);
const keyword = ref("");
const deviceTypeFilter = ref<string>(""); // "" = 全部
const tableData = ref<Device[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

// 项目字典：id -> name
const projectMap = ref<Map<number, string>>(new Map());

const deviceTypeMeta: Record<string, { label: string; tag: "" | "success" | "warning" | "info" }> = {
  locate: { label: "人机定位", tag: "success" },
  anti_intrusion: { label: "大机防侵限", tag: "warning" },
  train_approach: { label: "列车接近", tag: "info" },
};

const statusTagType: Record<string, "" | "success" | "warning" | "info"> = {
  在线: "success",
  离线: "info",
  低电量: "warning",
};

function deviceTypeLabel(t: string): string {
  return deviceTypeMeta[t]?.label ?? t;
}
function deviceTypeTag(t: string): "" | "success" | "warning" | "info" {
  return deviceTypeMeta[t]?.tag ?? "";
}
function projectName(id: number | null): string {
  if (id == null) return "—";
  return projectMap.value.get(id) ?? `ID:${id}`;
}

async function loadProjects() {
  try {
    const all: Project[] = [];
    let p = 1;
    // 拉取前若干页填充下拉（主数据量级有限）
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
    const pageData = await fetchDevices({
      device_type: deviceTypeFilter.value || undefined,
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
  deviceTypeFilter.value = "";
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
  device_type: "locate" as DeviceType,
  project_id: undefined as number | undefined,
  name: "",
  device_no: "",
  sn: "",
  status: "在线",
  function: "",
  longitude: undefined as number | undefined,
  latitude: undefined as number | undefined,
  direction: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  device_type: [{ required: true, message: "请选择设备类型", trigger: "change" }],
  project_id: [{ required: true, message: "请选择归属项目", trigger: "change" }],
  name: [{ required: true, message: "请输入设备名称", trigger: "blur" }],
  device_no: [{ required: true, message: "请输入设备编号", trigger: "blur" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm());
  dialogVisible.value = true;
}

async function openEdit(row: Device) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    device_type: row.device_type,
    project_id: row.project_id ?? undefined,
    name: row.name,
    device_no: row.device_no,
    sn: row.sn ?? "",
    status: row.status,
    function: row.function ?? "",
    longitude: row.longitude ?? undefined,
    latitude: row.latitude ?? undefined,
    direction: row.direction ?? "",
  });
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const payload: DeviceCreate | DeviceUpdate = {
        device_type: form.device_type,
        project_id: form.project_id as number,
        name: form.name,
        device_no: form.device_no,
        sn: form.sn ? form.sn : null,
        status: form.status,
        function: form.function ? form.function : null,
        longitude: form.longitude ?? null,
        latitude: form.latitude ?? null,
        direction: form.direction ? form.direction : null,
      };
      if (dialogMode.value === "create") {
        await createDevice(payload as DeviceCreate);
        ElMessage.success("设备创建成功");
      } else {
        await updateDevice(
          editingId.value as number,
          (payload as DeviceCreate).device_type,
          payload as DeviceUpdate,
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

async function handleDelete(row: Device) {
  try {
    await ElMessageBox.confirm(
      `确定删除设备「${row.name}」吗？该操作将软删设备。`,
      "删除确认",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await deleteDevice(row.id, row.device_type);
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
  loadProjects();
  loadData();
});
</script>

<template>
  <div class="device-page">
    <div class="toolbar">
      <el-select v-model="deviceTypeFilter" placeholder="设备类型" clearable class="filter-select">
        <el-option label="全部类型" value="" />
        <el-option label="人机定位" value="locate" />
        <el-option label="大机防侵限" value="anti_intrusion" />
        <el-option label="列车接近" value="train_approach" />
      </el-select>
      <el-input
        v-model="keyword"
        placeholder="按名称/编号搜索"
        clearable
        class="search-input"
        @keyup.enter="handleSearch"
        @clear="handleReset"
      />
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增设备</el-button>
    </div>

    <el-table v-loading="loading" :data="tableData" border stripe class="table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="设备名称" min-width="140" show-overflow-tooltip />
      <el-table-column prop="device_no" label="设备编号" width="130" show-overflow-tooltip />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="deviceTypeTag(row.device_type)">{{ deviceTypeLabel(row.device_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status] || ''">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="归属项目" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column v-if="tableData.some(r => r.device_type === 'locate')" label="功能" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ row.device_type === 'locate' ? (row.function || '—') : '—' }}</template>
      </el-table-column>
      <el-table-column v-if="tableData.some(r => r.device_type !== 'locate')" label="经纬度" width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.device_type !== 'locate'">
            {{ row.longitude ?? '—' }}, {{ row.latitude ?? '—' }}
          </span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column v-if="tableData.some(r => r.device_type === 'train_approach')" label="方位" width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ row.device_type === 'train_approach' ? (row.direction || '—') : '—' }}</template>
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
      :title="dialogMode === 'create' ? '新增设备' : '编辑设备'"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="设备类型" prop="device_type">
          <el-select v-model="form.device_type" :disabled="dialogMode === 'edit'" class="full">
            <el-option label="人机定位" value="locate" />
            <el-option label="大机防侵限" value="anti_intrusion" />
            <el-option label="列车接近" value="train_approach" />
          </el-select>
        </el-form-item>
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
        <el-form-item label="设备名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入设备名称" />
        </el-form-item>
        <el-form-item label="设备编号" prop="device_no">
          <el-input v-model="form.device_no" placeholder="唯一编号" />
        </el-form-item>
        <el-form-item label="SN码">
          <el-input v-model="form.sn" placeholder="设备SN码（可选）" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" class="full">
            <el-option label="在线" value="在线" />
            <el-option label="离线" value="离线" />
            <el-option label="低电量" value="低电量" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.device_type === 'locate'" label="功能">
          <el-input v-model="form.function" placeholder="设备功能描述" />
        </el-form-item>
        <template v-if="form.device_type !== 'locate'">
          <el-form-item label="经度">
            <el-input-number v-model="form.longitude" :precision="6" :controls="false" class="full" />
          </el-form-item>
          <el-form-item label="纬度">
            <el-input-number v-model="form.latitude" :precision="6" :controls="false" class="full" />
          </el-form-item>
        </template>
        <el-form-item v-if="form.device_type === 'train_approach'" label="方位">
          <el-input v-model="form.direction" placeholder="如：上行/下行" />
        </el-form-item>
      </el-form>
      <el-divider v-if="dialogMode === 'edit'" content-position="left">设备档案图 / 附件</el-divider>
      <AttachmentManager
        v-if="dialogMode === 'edit'"
        entity-type="device"
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
.device-page { padding: 4px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.search-input { width: 220px; }
.filter-select { width: 150px; }
.full { width: 100%; }
.table { width: 100%; }
.pager { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
