<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createMapAsset,
  deleteMapAsset,
  fetchMapAssets,
  updateMapAsset,
  type MapAsset,
  type MapAssetCreate,
  type MapAssetType,
} from "@/api/maps";
import { fetchProjects } from "@/api/project";
import type { Project } from "@/types";
import { uploadMedia } from "@/api/media";
import TablePager from "@/components/TablePager.vue";
import { batchDeleteMapAssets } from "@/api/maps";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";

// 资源类型下拉（前端本地枚举，与后端 constants.MAP_ASSET_TYPES 对齐）
const MAP_TYPE_OPTIONS: { value: MapAssetType; label: string }[] = [
  { value: "station_plan", label: "站点平面图" },
  { value: "plan_image", label: "平面图图片" },
  { value: "satellite", label: "卫星影像底图" },
  { value: "custom_basemap", label: "自定义底图" },
];
const mapTypeLabel = (t: string) =>
  MAP_TYPE_OPTIONS.find((o) => o.value === t)?.label ?? t;

const auth = useAuthStore();
const canAdd = computed(() => auth.hasPermission("map:add"));
const canEdit = computed(() => auth.hasPermission("map:edit"));
const canDelete = computed(
  () => auth.hasPermission("map:delete"),
);

const loading = ref(false);
const keyword = ref("");
const typeFilter = ref<MapAssetType | "">("");
const tableData = ref<MapAsset[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

const projectOptions = ref<Project[]>([]);

async function loadProjects() {
  try {
    const data = await fetchProjects({ page: 1, size: 1000 });
    projectOptions.value = data.items;
  } catch {
    projectOptions.value = [];
  }
}

function projectName(id: number | null) {
  if (id == null) return "-";
  return projectOptions.value.find((p) => p.id === id)?.name ?? `项目#${id}`;
}

async function load() {
  loading.value = true;
  try {
    const data = await fetchMapAssets({
      keyword: keyword.value || undefined,
      asset_type: typeFilter.value || undefined,
      page: page.value,
      size: size.value,
    });
    tableData.value = data.items;
    total.value = data.total;
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.value = 1;
  load();
}

// ----- 新增/编辑 -----
const dialogVisible = ref(false);
const editing = ref<MapAsset | null>(null);
const formRef = ref<FormInstance>();
const uploading = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const form = reactive<MapAssetCreate & { id?: number }>({
  name: "",
  type: "station_plan",
  project_id: null,
  center_lng: null,
  center_lat: null,
  zoom: null,
  coverage_wkt: null,
  image_url: null,
  remark: null,
  operator: null,
});

const rules: FormRules = {
  name: [{ required: true, message: "请输入资源名称", trigger: "blur" }],
  type: [{ required: true, message: "请选择资源类型", trigger: "change" }],
};

function openDialog(row?: MapAsset) {
  editing.value = row ?? null;
  form.id = row?.id;
  form.name = row?.name ?? "";
  form.type = row?.type ?? "station_plan";
  form.project_id = row?.project_id ?? null;
  form.center_lng = row?.center_lng ?? null;
  form.center_lat = row?.center_lat ?? null;
  form.zoom = row?.zoom ?? null;
  form.coverage_wkt = row?.coverage_wkt ?? null;
  form.image_url = row?.image_url ?? null;
  form.remark = row?.remark ?? null;
  form.operator = row?.operator ?? null;
  dialogVisible.value = true;
}

async function onUpload(e: Event) {
  const input = e.target as HTMLInputElement;
  if (!input.files || input.files.length === 0) return;
  uploading.value = true;
  try {
    const metas = await uploadMedia(Array.from(input.files), "maps");
    if (metas.length > 0) {
      form.image_url = metas[0].url;
      ElMessage.success("上传成功");
    }
  } finally {
    uploading.value = false;
    input.value = "";
  }
}

function triggerUpload() {
  fileInput.value?.click();
}

async function submit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid) => {
    if (!valid) return;
    const payload: MapAssetCreate = {
      name: form.name.trim(),
      type: form.type,
      project_id: form.project_id,
      center_lng: form.center_lng,
      center_lat: form.center_lat,
      zoom: form.zoom,
      coverage_wkt: form.coverage_wkt || null,
      image_url: form.image_url || null,
      remark: form.remark || null,
      operator: form.operator || null,
    };
    if (editing.value) {
      await updateMapAsset(editing.value.id, payload);
      ElMessage.success("更新成功");
    } else {
      await createMapAsset(payload);
      ElMessage.success("创建成功");
    }
    dialogVisible.value = false;
    load();
  });
}

async function remove(row: MapAsset) {
  await ElMessageBox.confirm(`确认删除地图资源「${row.name}」？`, "删除确认", {
    type: "warning",
  });
  await deleteMapAsset(row.id);
  ElMessage.success("删除成功");
  load();
}

onMounted(() => {
  loadProjects();
  load();
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
  deleteApi: batchDeleteMapAssets,
  reload: () => load(),
  label: "地图资源",
});
</script>

<template>
  <div class="map-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>地图资源库</span>
          <div class="toolbar">
            <el-input
              v-model="keyword"
              placeholder="名称/备注/维护人搜索"
              clearable
              style="width: 200px"
              @keyup.enter="handleSearch"
              @clear="handleSearch"
            />
            <el-select
              v-model="typeFilter"
              placeholder="资源类型"
              clearable
              style="width: 150px"
              @change="handleSearch"
            >
              <el-option
                v-for="o in MAP_TYPE_OPTIONS"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
            <el-button type="primary" @click="handleSearch">查询</el-button>
            <el-button v-if="canAdd" type="success" @click="openDialog()">新增资源</el-button>
          </div>
        </div>
      </template>

      <BatchActions
        v-if="canDelete"
        :selected="selectedRows.length"
        :loading="batchDeleting"
        @batch-delete="onBatchDelete"
        @clear="clearSelection"
      />
      <el-table v-loading="loading" :data="tableData" row-key="id" ref="tableRef" @selection-change="onSelectionChange">
        <el-table-column v-if="canDelete" type="selection" width="48" :reserve-selection="true" fixed="left" />
        <el-table-column label="序号" width="64" align="center">
          <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="类型" width="130">
          <template #default="{ row }">
            <el-tag size="small">{{ mapTypeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关联项目" min-width="130">
          <template #default="{ row }">{{ projectName(row.project_id) }}</template>
        </el-table-column>
        <el-table-column label="默认视图" min-width="170">
          <template #default="{ row }">
            <span v-if="row.center_lng != null && row.center_lat != null">
              {{ row.center_lng }}, {{ row.center_lat }}
              <span v-if="row.zoom != null">· Z{{ row.zoom }}</span>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="图片" width="90">
          <template #default="{ row }">
            <a v-if="row.image_url" :href="row.image_url" target="_blank" rel="noopener">
              查看
            </a>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="operator" label="维护人" width="100" />
        <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canEdit"
              link
              type="primary"
              size="small"
              @click="openDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="canDelete"
              link
              type="danger"
              size="small"
              @click="remove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <TablePager v-model:page="page" v-model:size="size" :total="total" :selected="selectedRows.length" @change="load" />
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑地图资源' : '新增地图资源'"
      width="560px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如 XX站平面图" />
        </el-form-item>
        <el-form-item label="类型" prop="type">
          <el-select v-model="form.type" style="width: 100%">
            <el-option
              v-for="o in MAP_TYPE_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="关联项目">
          <el-select
            v-model="form.project_id"
            placeholder="可选"
            clearable
            style="width: 100%"
          >
            <el-option
              v-for="p in projectOptions"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="中心经度">
          <el-input-number v-model="form.center_lng" :precision="6" :controls="false" />
        </el-form-item>
        <el-form-item label="中心纬度">
          <el-input-number v-model="form.center_lat" :precision="6" :controls="false" />
        </el-form-item>
        <el-form-item label="缩放级别">
          <el-input-number v-model="form.zoom" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="覆盖区域">
          <el-input v-model="form.coverage_wkt" type="textarea" :rows="2" placeholder="WKT 多边形" />
        </el-form-item>
        <el-form-item label="平面图/底图">
          <div class="upload-row">
            <el-input v-model="form.image_url" placeholder="MinIO 链接（可手动粘贴）" />
            <input ref="fileInput" type="file" accept="image/*" hidden @change="onUpload" />
            <el-button :loading="uploading" @click="triggerUpload">上传</el-button>
          </div>
        </el-form-item>
        <el-form-item label="维护人">
          <el-input v-model="form.operator" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.map-page {
  padding: 4px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.toolbar {
  display: flex;
  gap: 8px;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.upload-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
</style>
