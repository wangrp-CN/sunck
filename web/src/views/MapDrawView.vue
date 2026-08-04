<script setup lang="ts">
/**
 * 地图维护 · 手动绘制（系统管理·⑧）
 *
 * 用于人工补录/纠偏未及时刷新的道路或地点：
 * - 画点：自由画点（地图点击）/ 坐标画点（输入经纬度）
 * - 画线：自由画线（地图点击折点）/ 沿路画线（沿道路自动生成路径）
 * 每种模式均可「取消」放弃或「保存」持久化至地图。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import MapDrawCanvas from "@/components/MapDrawCanvas.vue";
import type { DrawMode, SavedDrawing } from "@/components/map-draw.types";
import {
  createMapDrawing,
  deleteMapDrawing,
  fetchMapDrawings,
  updateMapDrawing,
  type MapDrawing,
  type MapDrawingKind,
  type MapDrawingMode,
} from "@/api/map_drawings";
import { fetchProjects } from "@/api/project";
import type { Project } from "@/types";

// ---------------------------------------------------------------- 权限
const auth = useAuthStore();
const canAdd = computed(() => auth.hasPermission("map:add"));
const canEdit = computed(() => auth.hasPermission("map:edit"));
const canDelete = computed(
  () => auth.hasPermission("map:delete"),
);

// ---------------------------------------------------------------- 绘制模式
interface ModeOption {
  key: Exclude<DrawMode, "idle">;
  label: string;
  kind: MapDrawingKind;
  mode: MapDrawingMode;
  desc: string;
}

const MODE_OPTIONS: ModeOption[] = [
  {
    key: "point-free",
    label: "自由画点",
    kind: "point",
    mode: "free",
    desc: "在地图上点击标点",
  },
  {
    key: "point-coord",
    label: "坐标画点",
    kind: "point",
    mode: "coord",
    desc: "输入经纬度精确标点",
  },
  {
    key: "line-free",
    label: "自由画线",
    kind: "line",
    mode: "free",
    desc: "点击地图连续添加折点",
  },
  {
    key: "line-road",
    label: "沿路画线",
    kind: "line",
    mode: "road",
    desc: "沿道路自动生成路径",
  },
];

const KIND_LABELS: Record<string, string> = { point: "标注点", line: "标注线" };
const MODE_LABELS: Record<string, string> = {
  free: "自由绘制",
  coord: "坐标录入",
  road: "沿路绘制",
};

const drawMode = ref<DrawMode>("idle");
const activeOption = computed(() => MODE_OPTIONS.find((m) => m.key === drawMode.value) ?? null);
const isPointMode = computed(() => activeOption.value?.kind === "point");
const isLineMode = computed(() => activeOption.value?.kind === "line");
const isCoordMode = computed(() => drawMode.value === "point-coord");

const draftPoints = ref<number[][]>([]);
const canvasRef = ref<InstanceType<typeof MapDrawCanvas> | null>(null);

const form = reactive({
  name: "",
  project_id: null as number | null,
  color: "#f56c6c",
  remark: "",
});
const coordLng = ref<string>("");
const coordLat = ref<string>("");
const nameInvalid = ref(false);

function selectMode(key: Exclude<DrawMode, "idle">) {
  if (!canAdd.value) {
    ElMessage.warning("无地图标注新增权限");
    return;
  }
  if (drawMode.value === key) return;
  drawMode.value = key;
  resetDraft();
}

function resetDraft() {
  draftPoints.value = [];
  nameInvalid.value = false;
  canvasRef.value?.clearDraft?.();
}

function onDraftChange(v: number[][]) {
  draftPoints.value = v;
  if (isCoordMode.value && v.length === 1) {
    coordLng.value = String(v[0][0]);
    coordLat.value = String(v[0][1]);
  }
}

function applyCoord() {
  const lng = Number(coordLng.value);
  const lat = Number(coordLat.value);
  if (!coordLng.value || !coordLat.value || Number.isNaN(lng) || Number.isNaN(lat)) {
    ElMessage.warning("请输入合法的经纬度");
    return;
  }
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) {
    ElMessage.warning("经度需在 -180~180、纬度需在 -90~90 之间");
    return;
  }
  draftPoints.value = [[lng, lat]];
  canvasRef.value?.focusOn?.([[lng, lat]]);
}

function undoPoint() {
  canvasRef.value?.undo?.();
}

function clearPoints() {
  draftPoints.value = [];
  canvasRef.value?.clearDraft?.();
}

// 取消：放弃当前绘制并退出绘制模式
function handleCancel() {
  drawMode.value = "idle";
  draftPoints.value = [];
  form.name = "";
  form.remark = "";
  coordLng.value = "";
  coordLat.value = "";
  nameInvalid.value = false;
  canvasRef.value?.clearDraft?.();
  ElMessage.info("已取消当前绘制");
}

const saving = ref(false);

// 保存：校验必填名称与几何后落库
async function handleSave() {
  const opt = activeOption.value;
  if (!opt) {
    ElMessage.warning("请先选择绘制模式");
    return;
  }
  const name = form.name.trim();
  if (!name) {
    nameInvalid.value = true;
    ElMessage.warning(opt.kind === "point" ? "请填写点名称" : "请填写线名称");
    return;
  }
  nameInvalid.value = false;
  if (opt.kind === "point" && draftPoints.value.length !== 1) {
    ElMessage.warning("请先在地图上标注 1 个点");
    return;
  }
  if (opt.kind === "line" && draftPoints.value.length < 2) {
    ElMessage.warning("画线至少需要 2 个折点");
    return;
  }
  saving.value = true;
  try {
    await createMapDrawing({
      name,
      kind: opt.kind,
      mode: opt.mode,
      points: draftPoints.value,
      project_id: form.project_id,
      color: form.color,
      remark: form.remark || null,
    });
    ElMessage.success("保存成功，已持久化至地图");
    form.name = "";
    form.remark = "";
    coordLng.value = "";
    coordLat.value = "";
    resetDraft();
    await load();
  } finally {
    saving.value = false;
  }
}

// ---------------------------------------------------------------- 列表
const loading = ref(false);
const keyword = ref("");
const kindFilter = ref<MapDrawingKind | "">("");
const modeFilter = ref<MapDrawingMode | "">("");
const tableData = ref<MapDrawing[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);
const showSaved = ref(true);
const highlightId = ref<number | null>(null);

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
    const data = await fetchMapDrawings({
      keyword: keyword.value || undefined,
      kind: kindFilter.value || undefined,
      mode: modeFilter.value || undefined,
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

const savedShapes = computed<SavedDrawing[]>(() =>
  showSaved.value
    ? tableData.value.map((d) => ({
        id: d.id,
        name: d.name,
        kind: d.kind,
        points: d.points || [],
        color: d.color,
      }))
    : [],
);

function locate(row: MapDrawing) {
  highlightId.value = row.id;
  canvasRef.value?.focusOn?.(row.points || []);
}

async function rename(row: MapDrawing) {
  const res = await ElMessageBox.prompt(
    `重命名标注「${row.name}」`,
    row.kind === "point" ? "点名称" : "线名称",
    { inputValue: row.name, inputPattern: /\S+/, inputErrorMessage: "名称不能为空" },
  );
  const value = (res as { value?: string })?.value ?? "";
  if (!value.trim()) return;
  await updateMapDrawing(row.id, { name: value.trim() });
  ElMessage.success("更新成功");
  await load();
}

async function remove(row: MapDrawing) {
  await ElMessageBox.confirm(`确认删除标注「${row.name}」？`, "删除确认", {
    type: "warning",
  });
  await deleteMapDrawing(row.id);
  ElMessage.success("删除成功");
  if (highlightId.value === row.id) highlightId.value = null;
  await load();
}

function fmtLength(v: number | null) {
  if (v == null) return "-";
  return v >= 1000 ? `${(v / 1000).toFixed(2)} km` : `${v.toFixed(0)} m`;
}

onMounted(() => {
  loadProjects();
  load();
});
</script>

<template>
  <div class="map-draw-view">
    <!-- 工具条 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <span class="toolbar-title">绘制模式</span>
        <div class="mode-group">
          <button
            v-for="m in MODE_OPTIONS"
            :key="m.key"
            type="button"
            class="mode-btn"
            :class="{ active: drawMode === m.key }"
            :disabled="!canAdd"
            @click="selectMode(m.key)"
          >
            <span class="mode-label">{{ m.label }}</span>
            <span class="mode-desc">{{ m.desc }}</span>
          </button>
        </div>
        <el-tag v-if="activeOption" type="warning" effect="plain" class="state-tag">
          绘制中：{{ activeOption.label }}
        </el-tag>
        <el-tag v-else type="info" effect="plain" class="state-tag">未开始绘制</el-tag>
        <div class="toolbar-right">
          <el-switch v-model="showSaved" active-text="显示已保存标注" />
        </div>
      </div>
    </el-card>

    <!-- 地图 + 属性面板 -->
    <div class="draw-layout">
      <el-card shadow="never" class="map-card">
        <MapDrawCanvas
          ref="canvasRef"
          :draw-mode="drawMode"
          :points="draftPoints"
          :saved="savedShapes"
          :highlight-id="highlightId"
          :color="form.color"
          @update:points="onDraftChange"
        />
      </el-card>

      <el-card shadow="never" class="side-card">
        <template #header>
          <span class="side-title">标注属性</span>
        </template>

        <el-form label-width="76px" label-position="left" size="default">
          <el-form-item :label="isLineMode ? '线名称' : '点名称'" required>
            <el-input
              v-model="form.name"
              placeholder="必填，如：新增便道口"
              maxlength="128"
              :class="{ 'is-invalid': nameInvalid }"
              clearable
            />
          </el-form-item>
          <div v-if="nameInvalid" class="field-error">
            {{ isLineMode ? "线名称为必填项" : "点名称为必填项" }}
          </div>

          <el-form-item label="关联项目">
            <el-select v-model="form.project_id" placeholder="可选" clearable style="width: 100%">
              <el-option v-for="p in projectOptions" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>

          <el-form-item label="颜色">
            <el-color-picker v-model="form.color" />
          </el-form-item>

          <template v-if="isCoordMode">
            <el-form-item label="经度">
              <el-input v-model="coordLng" placeholder="如 116.397428" />
            </el-form-item>
            <el-form-item label="纬度">
              <el-input v-model="coordLat" placeholder="如 39.90923" />
            </el-form-item>
            <el-form-item label=" ">
              <el-button size="small" @click="applyCoord">在地图上定位</el-button>
            </el-form-item>
          </template>

          <el-form-item label="备注">
            <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="255" />
          </el-form-item>
        </el-form>

        <div class="draft-info">
          <span>已采集节点：<b>{{ draftPoints.length }}</b></span>
          <div v-if="isLineMode" class="draft-ops">
            <el-button size="small" text :disabled="draftPoints.length === 0" @click="undoPoint">
              撤销
            </el-button>
            <el-button size="small" text :disabled="draftPoints.length === 0" @click="clearPoints">
              清空
            </el-button>
          </div>
          <div v-else-if="isPointMode" class="draft-ops">
            <el-button size="small" text :disabled="draftPoints.length === 0" @click="clearPoints">
              清除点
            </el-button>
          </div>
        </div>

        <div class="side-actions">
          <el-button :disabled="!activeOption" @click="handleCancel">取消</el-button>
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!activeOption || !canAdd"
            @click="handleSave"
          >
            保存
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 已保存标注 -->
    <el-card shadow="never" class="list-card">
      <template #header>
        <div class="list-header">
          <span class="side-title">已保存标注</span>
          <div class="filters">
            <el-input
              v-model="keyword"
              placeholder="名称/备注/标注人"
              clearable
              style="width: 200px"
              @keyup.enter="handleSearch"
            />
            <el-select v-model="kindFilter" placeholder="类型" clearable style="width: 120px">
              <el-option label="标注点" value="point" />
              <el-option label="标注线" value="line" />
            </el-select>
            <el-select v-model="modeFilter" placeholder="模式" clearable style="width: 130px">
              <el-option label="自由绘制" value="free" />
              <el-option label="坐标录入" value="coord" />
              <el-option label="沿路绘制" value="road" />
            </el-select>
            <el-button type="primary" @click="handleSearch">查询</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="tableData" size="small" border stripe>
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'point' ? 'primary' : 'success'">
              {{ KIND_LABELS[row.kind] || row.kind }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模式" width="100">
          <template #default="{ row }">{{ MODE_LABELS[row.mode] || row.mode }}</template>
        </el-table-column>
        <el-table-column label="关联项目" min-width="130">
          <template #default="{ row }">{{ projectName(row.project_id) }}</template>
        </el-table-column>
        <el-table-column label="节点数" width="80">
          <template #default="{ row }">{{ (row.points || []).length }}</template>
        </el-table-column>
        <el-table-column label="长度" width="100">
          <template #default="{ row }">{{ fmtLength(row.length_m) }}</template>
        </el-table-column>
        <el-table-column prop="operator" label="标注人" width="110" />
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="locate(row)">定位</el-button>
            <el-button v-if="canEdit" size="small" text @click="rename(row)">重命名</el-button>
            <el-button v-if="canDelete" size="small" text type="danger" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next, jumper" @size-change="(s: number) => { size = s; }" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.map-draw-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-title {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.mode-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.mode-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color);
  background: var(--el-fill-color-blank);
  cursor: pointer;
  transition: all 0.15s ease;
}
.mode-btn:hover:not(:disabled) {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}
.mode-btn.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.mode-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.mode-label {
  font-size: 13px;
  font-weight: 600;
}
.mode-desc {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.state-tag {
  margin-left: 4px;
}
.toolbar-right {
  margin-left: auto;
}
.draw-layout {
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.map-card {
  flex: 1 1 auto;
  min-width: 0;
}
.map-card :deep(.el-card__body) {
  padding: 8px;
  height: 100%;
}
.side-card {
  width: 320px;
  flex: 0 0 320px;
}
.side-title {
  font-weight: 600;
}
.field-error {
  margin: -12px 0 12px 76px;
  font-size: 12px;
  color: var(--el-color-danger);
}
.is-invalid :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.draft-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.side-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
.side-actions .el-button {
  flex: 1;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
@media (max-width: 1100px) {
  .draw-layout {
    flex-direction: column;
  }
  .side-card {
    width: 100%;
    flex: 1 1 auto;
  }
}
</style>
