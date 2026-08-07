<script setup lang="ts">
/**
 * 电子围栏列表（原型《电子围栏列表》/《新增-编辑-查看电子围栏》）。
 *
 * 搜索区：项目名称（下拉，当前用户可见项目）、围栏名称（左右模糊）、
 *         围栏类型（普通防区/预警防区/报警防区）、围栏启用（是/否）+ 查询/重置/新增。
 * 列表区：按创建时间倒序，列 = 序号/项目名称/围栏名称/围栏类型/围栏启用/创建时间/操作。
 * 弹窗：新增 / 编辑 / 查看 三态复用，含「标点详情」经纬度表格（向上增加/向下增加/删除）
 *       与高德地图绘制联动；标点坐标以 GCJ-02（地图坐标）展示，落库前转 WGS-84 WKT。
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
  batchDeleteFences,
  createFence,
  deleteFence,
  fetchFences,
  updateFence,
} from "@/api/fence";
import { fetchProjects } from "@/api/project";
import MapPanel from "@/components/MapPanel.vue";
import TablePager from "@/components/TablePager.vue";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import { FENCE_TYPES } from "@/types";
import type {
  Fence,
  FenceCreate,
  FenceListParams,
  FenceUpdate,
  MapFence,
  Project,
} from "@/types";
import { gcj02ToWgs84, parseWktToGcjPath, pointsToWkt } from "@/utils/geo";

const auth = useAuthStore();
const route = useRoute();

// 权限门控（后端仍会二次校验）；hasPermission 兼容超管（permission_codes 可能为空）
const canAdd = computed(() => auth.hasPermission("fence:add"));
const canEdit = computed(() => auth.hasPermission("fence:edit"));
const canDelete = computed(() => auth.hasPermission("fence:delete"));

const loading = ref(false);
const tableData = ref<Fence[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);

// 项目下拉（当前用户数据范围内的项目，后端已按 DataScope 过滤）
const projects = ref<Project[]>([]);

/** 围栏类型标签色：普通=蓝 / 预警=橙 / 报警=红，与告警级别配色语义一致 */
const fenceTypeTag: Record<string, "primary" | "warning" | "danger"> = {
  普通防区: "primary",
  预警防区: "warning",
  报警防区: "danger",
};

/** 围栏描述预设项（示例，可按项目实际扩展；allow-create 允许用户自由输入新描述） */
const descriptionOptions: string[] = [
  "临近正线，重点监控",
  "施工便道入口",
  "材料堆场边界",
  "大型机械作业区",
  "人员通行通道",
];

// ---- 查询条件（对齐原型搜索区）----
const query = reactive({
  project_id: null as number | null,
  name: "",
  fence_type: null as string | null,
  enabled: null as boolean | null,
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

function projectName(row: Fence): string {
  if (row.project_name) return row.project_name;
  if (row.project_id == null) return "—";
  const hit = projects.value.find((p) => p.id === row.project_id);
  return hit ? hit.name : `ID:${row.project_id}`;
}

function buildParams(): FenceListParams {
  return {
    project_id: query.project_id ?? undefined,
    name: query.name.trim() || undefined,
    fence_type: query.fence_type ?? undefined,
    enabled: query.enabled ?? undefined,
    page: page.value,
    size: size.value,
  };
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchFences(buildParams());
    tableData.value = pageData.items;
    total.value = pageData.total;
  } catch {
    // 拦截器已统一提示
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
  query.fence_type = null;
  query.enabled = null;
  page.value = 1;
  loadData();
}

// ---- 标点详情（经纬度表格，GCJ-02 地图坐标）----
type MarkPoint = { lng: number | null; lat: number | null };

const points = ref<MarkPoint[]>([]);

function blankPoint(): MarkPoint {
  return { lng: null, lat: null };
}

/** 向上增加一行（在当前行之前插入空行，可手工录入经纬度） */
function addPointAbove(index: number) {
  points.value.splice(index, 0, blankPoint());
}

/** 向下增加一行（在当前行之后插入空行） */
function addPointBelow(index: number) {
  points.value.splice(index + 1, 0, blankPoint());
}

/** 删除当前行（同步移除地图上的对应顶点） */
function removePoint(index: number) {
  points.value.splice(index, 1);
}

/** 清空所有标点 */
function clearPoints() {
  points.value = [];
}

/** 有效顶点（经纬度均已填写且为合法数值） */
const validPoints = computed<[number, number][]>(() =>
  points.value
    .filter(
      (p) =>
        p.lng != null &&
        p.lat != null &&
        !Number.isNaN(Number(p.lng)) &&
        !Number.isNaN(Number(p.lat)),
    )
    .map((p) => [Number(p.lng), Number(p.lat)] as [number, number]),
);

/** 由标点实时生成的 WGS-84 WKT（不足 3 点返回 null） */
const geometryWkt = computed<string | null>(() => {
  const wgs = validPoints.value.map((p) => gcj02ToWgs84(p[0], p[1]));
  return pointsToWkt(wgs);
});

/** 地图预览围栏：随标点表格实时联动 */
const previewFences = computed<MapFence[]>(() => {
  const wkt = geometryWkt.value;
  if (!wkt) return [];
  return [{ id: editingId.value ?? -1, name: form.name || "围栏预览", geometry_wkt: wkt }];
});

/** 地图绘制完成（GCJ-02 顶点）→ 覆盖标点表格 */
function onFenceDrawn(payload: { points: [number, number][] }) {
  if (!payload.points || payload.points.length < 3) {
    ElMessage.warning("围栏至少需要 3 个顶点");
    return;
  }
  points.value = payload.points.map(([lng, lat]) => ({
    lng: Number(lng.toFixed(6)),
    lat: Number(lat.toFixed(6)),
  }));
  ElMessage.success("已生成 " + points.value.length + " 个标点，可在左侧微调经纬度");
}

/** WKT（WGS-84）→ 标点表格（GCJ-02），去掉 WKT 末尾的闭合重复点 */
function wktToPoints(wkt: string | null): MarkPoint[] {
  const path = parseWktToGcjPath(wkt);
  if (path.length === 0) return [];
  const ring = [...path];
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (ring.length > 1 && first[0] === last[0] && first[1] === last[1]) ring.pop();
  return ring.map(([lng, lat]) => ({
    lng: Number(lng.toFixed(6)),
    lat: Number(lat.toFixed(6)),
  }));
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
    ? "新增电子围栏"
    : dialogMode.value === "edit"
      ? "编辑电子围栏"
      : "查看电子围栏",
);

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  name: "",
  description: "",
  // 原型：围栏类型默认「普通防区」，围栏启用默认「是」
  fence_type: FENCE_TYPES[0] as string,
  enabled: true,
});

const form = reactive(emptyForm());

const rules: FormRules = {
  project_id: [{ required: true, message: "请选择项目名称", trigger: "change" }],
  name: [{ required: true, message: "请输入围栏名称", trigger: "blur" }],
  // 必填：用户必须显式选择围栏类型与启用状态后方可提交（沿用原型默认 普通防区 / 是）
  fence_type: [{ required: true, message: "请选择围栏类型", trigger: "change" }],
  enabled: [{ required: true, message: "请选择围栏启用状态", trigger: "change" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm(), {
    // 原型：默认为列表页当前筛选的项目
    project_id: query.project_id ?? undefined,
  });
  clearPoints();
  dialogVisible.value = true;
}

function fillForm(row: Fence) {
  editingId.value = row.id;
  Object.assign(form, emptyForm(), {
    project_id: row.project_id ?? undefined,
    name: row.name,
    description: row.description ?? "",
    fence_type: row.fence_type || FENCE_TYPES[0],
    enabled: row.enabled,
  });
  points.value = wktToPoints(row.geometry_wkt);
  dialogVisible.value = true;
}

function openEdit(row: Fence) {
  dialogMode.value = "edit";
  fillForm(row);
}

function openView(row: Fence) {
  dialogMode.value = "view";
  fillForm(row);
}

function buildFenceData(): FenceCreate {
  return {
    project_id: form.project_id as number,
    name: form.name.trim(),
    description: form.description ? form.description.trim() || null : null,
    fence_type: form.fence_type || null,
    enabled: form.enabled,
    geometry_wkt: geometryWkt.value,
  };
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    if (points.value.length > 0 && geometryWkt.value === null) {
      ElMessage.warning("围栏至少需要 3 个有效标点（经度、纬度均需填写）");
      return;
    }
    submitting.value = true;
    try {
      const payload = buildFenceData();
      if (dialogMode.value === "create") {
        await createFence(payload);
        ElMessage.success("电子围栏创建成功");
      } else {
        await updateFence(editingId.value as number, payload as FenceUpdate);
        ElMessage.success("电子围栏更新成功");
      }
      dialogVisible.value = false;
      loadData();
    } catch {
      // 拦截器已统一提示
    } finally {
      submitting.value = false;
    }
  });
}

async function handleDelete(row: Fence) {
  try {
    await ElMessageBox.confirm("您确认删除当前电子围栏？", "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await deleteFence(row.id);
    ElMessage.success("电子围栏已删除");
    loadData();
  } catch {
    // 拦截器已统一提示
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
  points,
  tableData,
  geometryWkt,
  previewFences,
  rules,
  descriptionOptions,
  buildFenceData,
  handleSearch,
  handleReset,
  openCreate,
  openEdit,
  openView,
  handleDelete,
  handleSubmit,
  onFenceDrawn,
  addPointAbove,
  addPointBelow,
  removePoint,
  clearPoints,
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
  deleteApi: batchDeleteFences,
  reload: () => loadData(),
  label: "电子围栏",
});
</script>

<template>
  <div class="fence-list-page">
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
        placeholder="围栏名称"
        clearable
        class="w-180"
        @keyup.enter="handleSearch"
      />
      <el-select v-model="query.fence_type" placeholder="围栏类型" clearable class="w-140">
        <el-option v-for="t in FENCE_TYPES" :key="t" :label="t" :value="t" />
      </el-select>
      <el-select v-model="query.enabled" placeholder="围栏启用" clearable class="w-120">
        <el-option label="是" :value="true" />
        <el-option label="否" :value="false" />
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
      <el-table-column prop="name" label="围栏名称" min-width="160" show-overflow-tooltip />
      <el-table-column label="围栏类型" width="120" align="center">
        <template #default="{ row }">
          <el-tag
            v-if="row.fence_type"
            :type="fenceTypeTag[row.fence_type] || 'info'"
            effect="light"
          >
            {{ row.fence_type }}
          </el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="围栏启用" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" effect="light">
            {{ row.enabled ? "是" : "否" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="180" fixed="right">
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
      width="1000px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="92px"
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
            <el-form-item label="围栏名称" prop="name">
              <el-input v-model="form.name" placeholder="请输入围栏名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="围栏类型" prop="fence_type">
              <el-select v-model="form.fence_type" class="full">
                <el-option v-for="t in FENCE_TYPES" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="围栏启用" prop="enabled">
              <el-select v-model="form.enabled" class="full">
                <el-option label="是" :value="true" />
                <el-option label="否" :value="false" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="围栏描述">
              <el-select
                v-model="form.description"
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="围栏描述（选填，可输入或从下拉选择）"
                class="full"
                popper-class="fence-desc-popper"
              >
                <el-option
                  v-for="opt in descriptionOptions"
                  :key="opt"
                  :label="opt"
                  :value="opt"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <!-- 围栏详情：左标点表格 + 右地图 -->
      <div class="fence-detail">
        <div class="detail-left">
          <div class="detail-title">
            <span>标点详情</span>
            <el-button
              v-if="!isView"
              link
              type="danger"
              :disabled="points.length === 0"
              @click="clearPoints"
            >
              清空标点
            </el-button>
          </div>
          <el-table :data="points" border size="small" height="300" class="point-table">
            <el-table-column label="标点序号" width="80" align="center">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column label="经度" min-width="120">
              <template #default="{ row }">
                <span v-if="isView">{{ row.lng ?? "—" }}</span>
                <el-input-number
                  v-else
                  v-model="row.lng"
                  :precision="6"
                  :step="0.0001"
                  :controls="false"
                  placeholder="经度"
                  class="full"
                />
              </template>
            </el-table-column>
            <el-table-column label="纬度" min-width="120">
              <template #default="{ row }">
                <span v-if="isView">{{ row.lat ?? "—" }}</span>
                <el-input-number
                  v-else
                  v-model="row.lat"
                  :precision="6"
                  :step="0.0001"
                  :controls="false"
                  placeholder="纬度"
                  class="full"
                />
              </template>
            </el-table-column>
            <el-table-column v-if="!isView" label="操作" width="220" align="center">
              <template #default="{ $index }">
                <div class="point-ops">
                  <el-button link type="primary" @click="addPointAbove($index)">
                    向上增加
                  </el-button>
                  <el-button link type="primary" @click="addPointBelow($index)">
                    向下增加
                  </el-button>
                  <el-button link type="danger" @click="removePoint($index)">删除</el-button>
                </div>
              </template>
            </el-table-column>
            <template #empty>
              <div class="point-empty">
                {{
                  isView
                    ? "该围栏未记录标点"
                    : "暂无标点：可在右侧地图点「绘制围栏」逐点勾勒，或点下方「新增标点」手工录入"
                }}
              </div>
            </template>
          </el-table>
          <div v-if="!isView" class="point-footer">
            <el-button
              type="primary"
              size="default"
              class="point-add-btn"
              @click="addPointBelow(points.length - 1)"
            >
              新增标点
            </el-button>
            <span class="point-tip">
              已录入 {{ points.length }} 点，有效 {{ validPoints.length }} 点（≥3 点方可成面）
            </span>
          </div>
        </div>
        <div class="detail-right">
          <MapPanel
            :devices="[]"
            :fences="previewFences"
            height="352px"
            @fence-draw="onFenceDrawn"
          />
        </div>
      </div>

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
.fence-list-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.w-120 {
  width: 120px;
}
.w-140 {
  width: 140px;
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

/* 围栏详情：左右分栏（标点表格 / 高德地图） */
.fence-detail {
  display: flex;
  gap: 12px;
  border-top: 1px dashed var(--el-border-color);
  padding-top: 12px;
}
.detail-left {
  flex: 0 0 480px;
  min-width: 0;
}
.detail-right {
  flex: 1;
  min-width: 0;
}
.detail-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}
.point-table {
  width: 100%;
}
.point-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  padding: 8px 12px;
}
.point-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
/* 「新增标点」高对比（主色实心）+ 加粗，便于快速识别与操作 */
.point-add-btn {
  font-weight: 600;
  letter-spacing: 1px;
  padding-left: 18px;
  padding-right: 18px;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.35);
}
.point-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
/* 标点操作按钮：flex 横向单行、不换行、居中、适中间距 */
.point-ops {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .fence-detail {
    flex-direction: column;
  }
  .detail-left {
    flex: 1 1 auto;
  }
}
</style>

<!-- 围栏描述下拉：弹层 teleport 到 body，必须用全局样式限制最大高度，超出滚动，避免无限下拉 -->
<style>
.fence-desc-popper .el-select-dropdown__wrap {
  max-height: 200px;
}
</style>
