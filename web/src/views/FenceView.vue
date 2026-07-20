<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createFence,
  deleteFence,
  fetchFences,
  updateFence,
} from "@/api/fence";
import { fetchProjects } from "@/api/project";
import MapPanel from "@/components/MapPanel.vue";
import type { Fence, FenceCreate, FenceUpdate, MapFence, Project } from "@/types";
import { gcj02ToWgs84, pointsToWkt } from "@/utils/geo";

const auth = useAuthStore();

const canAdd = computed(() => auth.user?.permission_codes.includes("fence:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("fence:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("fence:delete") ?? false);

const loading = ref(false);
const keyword = ref("");
const tableData = ref<Fence[]>([]);
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
    const pageData = await fetchFences({
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

// 地图绘制：预览围栏（绘制完成后回填 geometry_wkt 并在此上图）
const mapRefFence = ref<any>(null);
const previewFences = ref<MapFence[]>([]);

function onFenceDrawn(payload: { points: [number, number][] }) {
  const wgs = payload.points.map((p) => gcj02ToWgs84(p[0], p[1]));
  const wkt = pointsToWkt(wgs);
  if (!wkt) {
    ElMessage.warning("围栏至少需要 3 个顶点");
    return;
  }
  form.geometry_wkt = wkt;
  previewFences.value = [{ id: -1, name: "绘制预览", geometry_wkt: wkt }];
  ElMessage.success("围栏形状已绘制，可填写名称后保存");
}

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  name: "",
  fence_type: "",
  enabled: true,
  geometry_wkt: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  project_id: [{ required: true, message: "请选择归属项目", trigger: "change" }],
  name: [{ required: true, message: "请输入围栏名称", trigger: "blur" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm());
  previewFences.value = [];
  dialogVisible.value = true;
}

async function openEdit(row: Fence) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    project_id: row.project_id ?? undefined,
    name: row.name,
    fence_type: row.fence_type ?? "",
    enabled: row.enabled,
    geometry_wkt: row.geometry_wkt ?? "",
  });
  previewFences.value = row.geometry_wkt
    ? [{ id: row.id, name: row.name, geometry_wkt: row.geometry_wkt }]
    : [];
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const payload: FenceCreate | FenceUpdate = {
        project_id: form.project_id as number,
        name: form.name,
        fence_type: form.fence_type ? form.fence_type : null,
        enabled: form.enabled,
        geometry_wkt: form.geometry_wkt ? form.geometry_wkt : null,
      };
      if (dialogMode.value === "create") {
        await createFence(payload as FenceCreate);
        ElMessage.success("围栏创建成功");
      } else {
        await updateFence(editingId.value as number, payload as FenceUpdate);
        ElMessage.success("围栏更新成功");
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

async function handleDelete(row: Fence) {
  try {
    await ElMessageBox.confirm(
      `确定删除围栏「${row.name}」吗？该操作将软删围栏。`,
      "删除确认",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await deleteFence(row.id);
    ElMessage.success("围栏已删除");
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
  <div class="fence-page">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按名称/类型搜索"
        clearable
        class="search-input"
        @keyup.enter="handleSearch"
        @clear="handleReset"
      />
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增围栏</el-button>
    </div>

    <el-table v-loading="loading" :data="tableData" border stripe class="table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="围栏名称" min-width="160" show-overflow-tooltip />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">{{ row.fence_type || '—' }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="归属项目" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="几何(WKT)" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.geometry_wkt || '—' }}</template>
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
      :title="dialogMode === 'create' ? '新增围栏' : '编辑围栏'"
      width="620px"
      :close-on-click-modal="false"
      destroy-on-close
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
        <el-form-item label="围栏名称" prop="name">
          <el-input v-model="form.name" placeholder="围栏名称" />
        </el-form-item>
        <el-form-item label="围栏类型">
          <el-input v-model="form.fence_type" placeholder="如：人员/大机/列车" />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="几何(WKT)">
          <el-input
            v-model="form.geometry_wkt"
            type="textarea"
            :rows="3"
            placeholder="POLYGON((lng lat, ...)) 由高德地图绘制后回填"
          />
        </el-form-item>
      </el-form>
      <div class="draw-area">
        <div class="draw-tip">
          在下方地图点击「绘制围栏」按钮，逐点单击地图勾勒多边形；至少 3 点后点「完成」即可自动回填几何(WKT)。
        </div>
        <MapPanel
          ref="mapRefFence"
          :devices="[]"
          :fences="previewFences"
          height="320px"
          @fence-draw="onFenceDrawn"
        />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.fence-page { padding: 4px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.search-input { width: 240px; }
.full { width: 100%; }
.table { width: 100%; }
.pager { margin-top: 12px; display: flex; justify-content: flex-end; }
.draw-area { margin-top: 12px; border-top: 1px dashed #e4e7ed; padding-top: 12px; }
.draw-tip { font-size: 12px; color: #909399; margin-bottom: 8px; line-height: 1.5; }
</style>
