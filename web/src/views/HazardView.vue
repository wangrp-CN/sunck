<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  createHazard,
  deleteHazard,
  fetchHazardOptions,
  fetchHazardStats,
  fetchHazards,
  transitionHazard,
  updateHazard,
  type Hazard,
  type HazardLevel,
  type HazardOptions,
  type HazardStats,
  type HazardStatus,
} from "@/api/hazard";
import { fetchProjects } from "@/api/project";
import { fetchPersons } from "@/api/person";
import type { Person, Project } from "@/types";
import { useAuthStore } from "@/stores/auth";
import { wgs84ToGcj02 } from "@/utils/geo";
import MapPanel from "@/components/MapPanel.vue";

const auth = useAuthStore();
const canCreate = computed(() => auth.user?.permission_codes.includes("hazard:create") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("hazard:update") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("hazard:delete") ?? false);
const canHandle = computed(() => auth.user?.permission_codes.includes("hazard:handle") ?? false);

const options = ref<HazardOptions>({
  levels: ["重大", "较大", "一般", "低"],
  categories: ["施工安全", "设备设施", "环境", "管理", "其他"],
  sources: ["人工", "巡检", "系统"],
  statuses: ["待整改", "整改中", "待复核", "已销号", "已驳回"],
});

// 状态机流转动作（按当前状态给出可执行动作）
const TRANSITION_ACTIONS: Record<HazardStatus, { action: string; label: string; needNote: boolean }[]> = {
  待整改: [
    { action: "start_rectify", label: "开始整改", needNote: false },
    { action: "reject", label: "驳回隐患", needNote: true },
  ],
  整改中: [{ action: "submit_rectify", label: "提交整改（待复核）", needNote: true }],
  待复核: [
    { action: "verify_pass", label: "复核通过并销号", needNote: true },
    { action: "verify_reject", label: "复核驳回", needNote: true },
  ],
  已销号: [],
  已驳回: [{ action: "reopen", label: "重新打开", needNote: false }],
};

const projects = ref<Project[]>([]);
const persons = ref<Person[]>([]);
const list = ref<Hazard[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);
const stats = ref<HazardStats | null>(null);

const filters = reactive({
  project_id: null as number | null,
  level: "" as string,
  status: "" as string,
  keyword: "" as string,
  overdue: false as boolean,
});

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* 忽略 */
  }
}
async function loadPersons() {
  try {
    const res = await fetchPersons({ page: 1, size: 200 });
    persons.value = res.items;
  } catch {
    /* 忽略 */
  }
}

async function loadHazards() {
  loading.value = true;
  try {
    const res = await fetchHazards({
      project_id: filters.project_id ?? undefined,
      level: filters.level || undefined,
      status: filters.status || undefined,
      keyword: filters.keyword || undefined,
      overdue: filters.overdue,
      page: page.value,
      size: size.value,
    });
    list.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载隐患失败");
  } finally {
    loading.value = false;
  }
}

async function loadStats() {
  try {
    stats.value = await fetchHazardStats();
  } catch {
    /* 忽略 */
  }
}

function applyFilters() {
  page.value = 1;
  loadHazards();
}
function resetFilters() {
  filters.project_id = null;
  filters.level = "";
  filters.status = "";
  filters.keyword = "";
  filters.overdue = false;
  page.value = 1;
  loadHazards();
}
function onPageChange(p: number) {
  page.value = p;
  loadHazards();
}
function onSizeChange(s: number) {
  size.value = s;
  page.value = 1;
  loadHazards();
}

// ----- 创建 / 编辑 -----
const dialogVisible = ref(false);
const submitting = ref(false);
const editingId = ref<number | null>(null);
const form = reactive({
  project_id: null as number | null,
  title: "",
  level: "一般" as HazardLevel,
  category: "" as string,
  description: "" as string,
  location_desc: "" as string,
  lng: null as number | null,
  lat: null as number | null,
  discovered_by_name: "" as string,
  discovered_at: "" as string,
  source: "人工" as string,
  assignee_id: null as number | null,
  due_at: "" as string,
});

const mapRef = ref<any>(null);
const mapReady = ref(false);
function onMapReady() {
  mapReady.value = true;
  refreshMapMarker();
}
function refreshMapMarker() {
  if (!mapReady.value || !mapRef.value) return;
  if (form.lng != null && form.lat != null) {
    const [glng, glat] = wgs84ToGcj02(form.lng, form.lat);
    mapRef.value.setMovingMarker([glng, glat]);
  }
}
watch([() => dialogVisible.value, () => form.lng, () => form.lat], async () => {
  if (dialogVisible.value) {
    await nextTick();
    refreshMapMarker();
  }
});

function resetForm() {
  editingId.value = null;
  form.project_id = filters.project_id ?? null;
  form.title = "";
  form.level = "一般";
  form.category = "";
  form.description = "";
  form.location_desc = "";
  form.lng = null;
  form.lat = null;
  form.discovered_by_name = "";
  form.discovered_at = "";
  form.source = "人工";
  form.assignee_id = null;
  form.due_at = "";
}
function openCreate() {
  resetForm();
  mapReady.value = false;
  dialogVisible.value = true;
}
function openEdit(row: Hazard) {
  editingId.value = row.id;
  form.project_id = row.project_id;
  form.title = row.title;
  form.level = row.level;
  form.category = row.category ?? "";
  form.description = row.description ?? "";
  form.location_desc = row.location_desc ?? "";
  form.lng = row.lng;
  form.lat = row.lat;
  form.discovered_by_name = row.discovered_by_name ?? "";
  form.discovered_at = row.discovered_at ?? "";
  form.source = row.source;
  form.assignee_id = row.assignee_id;
  form.due_at = row.due_at ?? "";
  mapReady.value = false;
  dialogVisible.value = true;
}

async function submitForm() {
  if (!form.title.trim()) {
    ElMessage.warning("请填写隐患标题");
    return;
  }
  submitting.value = true;
  const payload = {
    project_id: form.project_id,
    title: form.title.trim(),
    level: form.level,
    category: form.category || null,
    description: form.description || null,
    location_desc: form.location_desc || null,
    lng: form.lng,
    lat: form.lat,
    discovered_by_name: form.discovered_by_name || null,
    discovered_at: form.discovered_at || null,
    source: form.source,
    assignee_id: form.assignee_id,
    due_at: form.due_at || null,
  };
  try {
    if (editingId.value != null) {
      await updateHazard(editingId.value, payload);
      ElMessage.success("隐患已更新");
    } else {
      await createHazard(payload);
      ElMessage.success("隐患已创建");
    }
    dialogVisible.value = false;
    await Promise.all([loadHazards(), loadStats()]);
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    submitting.value = false;
  }
}

// ----- 删除 -----
async function handleDelete(row: Hazard) {
  try {
    await deleteHazard(row.id);
    ElMessage.success("隐患已删除");
    await Promise.all([loadHazards(), loadStats()]);
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

// ----- 状态流转 -----
const transVisible = ref(false);
const transLoading = ref(false);
const transRow = ref<Hazard | null>(null);
const transAction = ref("");
const transNote = ref("");
const transActions = computed(() =>
  transRow.value ? TRANSITION_ACTIONS[transRow.value.status as HazardStatus] : [],
);
function openTransition(row: Hazard) {
  transRow.value = row;
  transAction.value = transActions.value[0]?.action ?? "";
  transNote.value = "";
  transVisible.value = true;
}
async function submitTransition() {
  if (!transRow.value || !transAction.value) return;
  const act = transActions.value.find((a) => a.action === transAction.value);
  if (act?.needNote && !transNote.value.trim()) {
    ElMessage.warning("该动作需填写说明");
    return;
  }
  transLoading.value = true;
  try {
    await transitionHazard(transRow.value.id, {
      action: transAction.value,
      note: transNote.value || null,
    });
    ElMessage.success("状态已更新");
    transVisible.value = false;
    await Promise.all([loadHazards(), loadStats()]);
  } catch (e: any) {
    ElMessage.error(e?.message || "流转失败");
  } finally {
    transLoading.value = false;
  }
}

// 标签样式
function levelTag(level: string): "" | "danger" | "warning" | "info" | "success" {
  if (level === "重大") return "danger";
  if (level === "较大") return "warning";
  if (level === "低") return "info";
  return "";
}
function statusTag(status: string): "" | "danger" | "warning" | "success" | "primary" {
  if (status === "待整改" || status === "已驳回") return "danger";
  if (status === "整改中" || status === "待复核") return "warning";
  if (status === "已销号") return "success";
  return "";
}
function projectName(id: number | null): string {
  return projects.value.find((p) => p.id === id)?.name ?? "—";
}
function personName(id: number | null): string {
  if (id == null) return "—";
  return persons.value.find((p) => p.id === id)?.name ?? `人员#${id}`;
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* 忽略 */
    }
  }
  try {
    options.value = await fetchHazardOptions();
  } catch {
    /* 用默认值 */
  }
  await Promise.all([loadProjects(), loadPersons()]);
  await loadHazards();
  await loadStats();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <el-form :inline="true" class="filters">
        <el-form-item label="项目">
          <el-select v-model="filters.project_id" placeholder="全部" clearable style="width: 160px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="filters.level" placeholder="全部" clearable style="width: 120px">
            <el-option v-for="lv in options.levels" :key="lv" :label="lv" :value="lv" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width: 120px">
            <el-option v-for="s in options.statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="filters.keyword" placeholder="标题/描述/位置" clearable style="width: 180px" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="filters.overdue">仅看超期</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyFilters">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
      <div class="bar-actions">
        <el-button v-if="canCreate" type="success" @click="openCreate">新增隐患</el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-cards" v-if="stats">
      <div class="stat-card">
        <div class="stat-num">{{ stats.total }}</div>
        <div class="stat-label">隐患总数</div>
      </div>
      <div class="stat-card warn">
        <div class="stat-num">{{ stats.overdue }}</div>
        <div class="stat-label">超期未整改</div>
      </div>
      <div class="stat-card" v-for="(cnt, st) in stats.by_status" :key="st">
        <div class="stat-num">{{ cnt }}</div>
        <div class="stat-label">{{ st }}</div>
      </div>
    </div>

    <el-table :data="list" v-loading="loading" border stripe style="width: 100%" row-key="id">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="隐患标题" min-width="160" show-overflow-tooltip />
      <el-table-column label="等级" width="90">
        <template #default="{ row }">
          <el-tag :type="levelTag(row.level)" effect="dark">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="类别" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status }}</el-tag>
          <el-tag v-if="row.is_overdue" type="danger" size="small" effect="plain" class="ov-tag">超期</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="项目" width="130">
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="整改责任人" width="110">
        <template #default="{ row }">{{ personName(row.assignee_id) }}</template>
      </el-table-column>
      <el-table-column label="发现人" width="100">
        <template #default="{ row }">{{ row.discovered_by_name || "—" }}</template>
      </el-table-column>
      <el-table-column label="整改期限" width="160">
        <template #default="{ row }">{{ row.due_at || "—" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canHandle" type="primary" link @click="openTransition(row)">流转</el-button>
          <el-button v-if="canEdit" type="info" link @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canDelete" type="danger" link @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无隐患</template>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <!-- 创建 / 编辑 弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId != null ? '编辑隐患' : '新增隐患'" width="720px" top="5vh">
      <el-form label-width="96px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="所属项目">
              <el-select v-model="form.project_id" placeholder="请选择" clearable style="width: 100%">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="隐患标题">
              <el-input v-model="form.title" placeholder="必填" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="等级">
              <el-select v-model="form.level" style="width: 100%">
                <el-option v-for="lv in options.levels" :key="lv" :label="lv" :value="lv" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="类别">
              <el-select v-model="form.category" placeholder="可选" clearable style="width: 100%">
                <el-option v-for="c in options.categories" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="来源">
              <el-select v-model="form.source" style="width: 100%">
                <el-option v-for="s in options.sources" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="隐患描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="隐患具体情况" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="位置描述">
              <el-input v-model="form.location_desc" placeholder="如：K123+200 桥墩旁" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="经度(WGS-84)">
              <el-input-number v-model="form.lng" :precision="6" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="纬度(WGS-84)">
              <el-input-number v-model="form.lat" :precision="6" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="发现人">
              <el-input v-model="form.discovered_by_name" placeholder="可选" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="发现时间">
              <el-date-picker
                v-model="form.discovered_at"
                type="datetime"
                value-format="YYYY-MM-DDTHH:mm:ss"
                placeholder="可选"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="整改责任人">
              <el-select v-model="form.assignee_id" placeholder="可选" clearable style="width: 100%">
                <el-option v-for="p in persons" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="整改期限">
          <el-date-picker
            v-model="form.due_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="可选"
            style="width: 240px"
          />
        </el-form-item>
        <el-form-item label="位置预览">
          <div class="map-box">
            <MapPanel ref="mapRef" :devices="[]" :fences="[]" height="240px" @ready="onMapReady" />
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 状态流转 弹窗 -->
    <el-dialog v-model="transVisible" title="隐患状态流转" width="460px">
      <template v-if="transRow">
        <el-descriptions :column="1" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="隐患">{{ transRow.title }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">{{ transRow.status }}</el-descriptions-item>
        </el-descriptions>
        <el-form label-width="80px">
          <el-form-item label="流转动作">
            <el-select v-model="transAction" style="width: 100%">
              <el-option
                v-for="a in transActions"
                :key="a.action"
                :label="a.label"
                :value="a.action"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="说明">
            <el-input
              v-model="transNote"
              type="textarea"
              :rows="3"
              :placeholder="transActions.find((a) => a.action === transAction)?.needNote ? '请填写说明（必填）' : '可选'"
            />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="transVisible = false">取消</el-button>
        <el-button type="primary" :loading="transLoading" @click="submitTransition">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.filters { flex-wrap: wrap; }
.bar-actions { display: flex; gap: 8px; flex-shrink: 0; }
.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  text-align: center;
}
.stat-card.warn { background: #fef0f0; border-color: #fde2e2; }
.stat-num { font-size: 22px; font-weight: 700; color: #303133; }
.stat-card.warn .stat-num { color: #f56c6c; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.ov-tag { margin-left: 4px; }
.pager { margin-top: 12px; color: #606266; font-size: 13px; }
.map-box { border: 1px solid #ebeef5; border-radius: 6px; overflow: hidden; }
</style>
