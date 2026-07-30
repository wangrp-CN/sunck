<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { fetchProjects } from "@/api/project";
import { searchKnowledge, type KnowledgeSearchItem } from "@/api/knowledge";
import {
  createPlaybook,
  deletePlaybook,
  getPlaybookMeta,
  listPlaybooks,
  updatePlaybook,
  type Playbook,
  type PlaybookMeta,
  type PlaybookPayload,
  type PlaybookRef,
} from "@/api/playbook";

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission("playbook:manage"));

const items = ref<Playbook[]>([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const size = ref(20);

const projects = ref<{ id: number; name: string }[]>([]);
const meta = ref<PlaybookMeta>({
  alarm_types: [],
  levels: ["提示", "警告", "严重"],
});

const filterProject = ref<number | null>(null);
const filterType = ref<string>("");
const filterLevel = ref<string>("");
const filterEnabled = ref<boolean | null>(null);

const levelTag: Record<string, string> = {
  提示: "info",
  警告: "warning",
  严重: "danger",
};

async function loadProjects() {
  try {
    const r = await fetchProjects({ page: 1, size: 200 });
    projects.value = (r.items || []).map((p: any) => ({ id: p.id, name: p.name }));
  } catch {
    projects.value = [];
  }
}

function typeLabel(key: string | null): string {
  if (!key) return "通用（全部类型）";
  return meta.value.alarm_types.find((t) => t.key === key)?.label || key;
}

async function load() {
  loading.value = true;
  try {
    const res = await listPlaybooks({
      project_id: filterProject.value || undefined,
      alarm_type: filterType.value || undefined,
      alarm_level: filterLevel.value || undefined,
      enabled: filterEnabled.value === null ? undefined : filterEnabled.value,
      page: page.value,
      size: size.value,
    });
    items.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载预案失败");
  } finally {
    loading.value = false;
  }
}

// ---- 新增 / 编辑 ----
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const form = ref({
  name: "",
  project_id: null as number | null,
  alarm_type: "" as string,
  alarm_level: "" as string,
  enabled: true,
  summary: "",
  steps: [] as string[],
  stepDraft: "",
  trigger_condition: "" as string,
  references: [] as PlaybookRef[],
  refTitle: "",
  refUrl: "",
  tags: "" as string,
  owner_role: "" as string,
  est_minutes: null as number | null,
  note: "" as string,
});

function resetForm() {
  form.value = {
    name: "",
    project_id: filterProject.value || null,
    alarm_type: "",
    alarm_level: "",
    enabled: true,
    summary: "",
    steps: [],
    stepDraft: "",
    trigger_condition: "",
    references: [],
    refTitle: "",
    refUrl: "",
    tags: "",
    owner_role: "",
    est_minutes: null,
    note: "",
  };
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: Playbook) {
  editingId.value = row.id;
  form.value = {
    name: row.name,
    project_id: row.project_id,
    alarm_type: row.alarm_type || "",
    alarm_level: row.alarm_level || "",
    enabled: row.enabled,
    summary: row.summary,
    steps: [...(row.steps || [])],
    stepDraft: "",
    trigger_condition: row.trigger_condition || "",
    references: (row.references || []).map((r) => ({ ...r })),
    refTitle: "",
    refUrl: "",
    tags: row.tags || "",
    owner_role: row.owner_role || "",
    est_minutes: row.est_minutes,
    note: row.note || "",
  };
  dialogVisible.value = true;
}

function addStep() {
  const s = form.value.stepDraft.trim();
  if (s) {
    form.value.steps.push(s);
    form.value.stepDraft = "";
  }
}
function removeStep(i: number) {
  form.value.steps.splice(i, 1);
}
function addRef() {
  if (form.value.refTitle.trim() || form.value.refUrl.trim()) {
    form.value.references.push({
      title: form.value.refTitle.trim(),
      url: form.value.refUrl.trim(),
    });
    form.value.refTitle = "";
    form.value.refUrl = "";
  }
}
function removeRef(i: number) {
  form.value.references.splice(i, 1);
}

// ---- 从知识库检索关联链接 ----
const kbDialogVisible = ref(false);
const kbQuery = ref("");
const kbLoading = ref(false);
const kbResults = ref<KnowledgeSearchItem[]>([]);

function openKbSearch() {
  // 预填检索词：预案名称/要点/标签
  kbQuery.value = [form.value.name, form.value.summary, form.value.tags]
    .filter(Boolean)
    .join(" ");
  kbResults.value = [];
  kbDialogVisible.value = true;
}

async function runKbSearch() {
  if (!kbQuery.value.trim()) {
    ElMessage.warning("请输入检索关键词");
    return;
  }
  kbLoading.value = true;
  try {
    kbResults.value = await searchKnowledge({ q: kbQuery.value.trim(), limit: 10 });
    if (kbResults.value.length === 0) {
      ElMessage.info("无匹配知识库条目");
    }
  } catch (e: any) {
    ElMessage.error(e?.message || "检索失败");
  } finally {
    kbLoading.value = false;
  }
}

function addKbOne(r: KnowledgeSearchItem) {
  const exists = form.value.references.some((x) => x.url === r.url);
  if (exists) {
    ElMessage.info("该链接已在预案中");
    return;
  }
  form.value.references.push({ title: r.title, url: r.url });
  ElMessage.success("已添加知识库链接");
}

async function submitForm() {
  if (!form.value.name.trim()) {
    ElMessage.warning("请填写预案名称");
    return;
  }
  if (!form.value.summary.trim()) {
    ElMessage.warning("请填写处置要点");
    return;
  }
  submitting.value = true;
  const payload: PlaybookPayload = {
    name: form.value.name.trim(),
    project_id: form.value.project_id || null,
    alarm_type: form.value.alarm_type || null,
    alarm_level: form.value.alarm_level || null,
    enabled: form.value.enabled,
    summary: form.value.summary.trim(),
    steps: form.value.steps,
    trigger_condition: form.value.trigger_condition || null,
    references: form.value.references,
    tags: form.value.tags || null,
    owner_role: form.value.owner_role || null,
    est_minutes: form.value.est_minutes || null,
    note: form.value.note || null,
  };
  try {
    if (editingId.value) {
      await updatePlaybook(editingId.value, payload);
      ElMessage.success("预案已更新");
    } else {
      await createPlaybook(payload);
      ElMessage.success("预案已新增");
    }
    dialogVisible.value = false;
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    submitting.value = false;
  }
}

async function removeRow(row: Playbook) {
  try {
    await ElMessageBox.confirm(`确认删除预案「${row.name}」？`, "删除确认", { type: "warning" });
  } catch {
    return;
  }
  try {
    await deletePlaybook(row.id);
    ElMessage.success("已删除");
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

onMounted(async () => {
  await loadProjects();
  try {
    meta.value = await getPlaybookMeta();
  } catch {
    /* 用默认 levels */
  }
  load();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <span class="title">处置预案（知识库）</span>
      <div class="bar-actions">
        <el-button v-if="canManage" type="primary" @click="openCreate">新增预案</el-button>
      </div>
    </div>

    <el-alert
      class="hint"
      title="处置预案按「项目 × 告警类型 × 级别」匹配，告警处置时自动推荐，形成闭环处置指导。系统已预置 6 类告警的通用预案（mock），可按项目细化覆盖。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="filters">
      <el-select v-model="filterProject as any" clearable placeholder="按项目筛选" style="width: 200px">
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-select v-model="filterType" clearable placeholder="按告警类型" style="width: 180px">
        <el-option label="全部类型" value="" />
        <el-option v-for="t in meta.alarm_types" :key="t.key" :label="t.label" :value="t.key" />
      </el-select>
      <el-select v-model="filterLevel" clearable placeholder="按级别" style="width: 140px">
        <el-option label="全部级别" value="" />
        <el-option v-for="l in meta.levels" :key="l" :label="l" :value="l" />
      </el-select>
      <el-select v-model="filterEnabled as any" clearable placeholder="启用状态" style="width: 140px">
        <el-option label="全部" :value="null" />
        <el-option label="已启用" :value="true" />
        <el-option label="已停用" :value="false" />
      </el-select>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="items" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="归属" min-width="110">
        <template #default="{ row }">{{ row.project_name || "全局" }}</template>
      </el-table-column>
      <el-table-column label="类型" min-width="110">
        <template #default="{ row }">{{ typeLabel(row.alarm_type) }}</template>
      </el-table-column>
      <el-table-column label="级别" width="90" align="center">
        <template #default="{ row }">
          <span v-if="row.alarm_level">
            <el-tag :type="(levelTag[row.alarm_level] as any)" size="small">{{ row.alarm_level }}</el-tag>
          </span>
          <span v-else class="muted">不限</span>
        </template>
      </el-table-column>
      <el-table-column label="要点" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ row.summary }}</template>
      </el-table-column>
      <el-table-column label="步骤数" width="80" align="center">
        <template #default="{ row }">{{ (row.steps || []).length }}</template>
      </el-table-column>
      <el-table-column label="责任岗位" min-width="100">
        <template #default="{ row }">{{ row.owner_role || "—" }}</template>
      </el-table-column>
      <el-table-column label="启用" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? "启用" : "停用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right" v-if="canManage">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无预案</template>
    </el-table>

    <el-pagination
      class="pager"
      :current-page="page"
      :page-size="size"
      :total="total"
      layout="prev, pager, next, total"
      @current-change="(p: number) => { page = p; load(); }"
    />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑预案' : '新增预案'"
      width="640px"
      top="5vh"
    >
      <el-form label-width="96px">
        <el-form-item label="预案名称" required>
          <el-input v-model="form.name" placeholder="如：电子围栏侵入处置预案" />
        </el-form-item>
        <el-form-item label="归属项目">
          <el-select v-model="form.project_id as any" clearable filterable placeholder="不选=全局通用" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警类型">
          <el-select v-model="form.alarm_type" clearable style="width: 100%">
            <el-option label="通用（全部类型）" value="" />
            <el-option v-for="t in meta.alarm_types" :key="t.key" :label="t.label" :value="t.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联级别">
          <el-select v-model="form.alarm_level" clearable style="width: 100%">
            <el-option label="不限级别" value="" />
            <el-option v-for="l in meta.levels" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="处置要点" required>
          <el-input v-model="form.summary" type="textarea" :rows="2" placeholder="一句话处置要点" />
        </el-form-item>
        <el-form-item label="触发条件">
          <el-input v-model="form.trigger_condition" type="textarea" :rows="2" placeholder="选填：触发本预案的条件说明" />
        </el-form-item>
        <el-divider>处置步骤</el-divider>
        <el-form-item label="新增步骤">
          <div class="step-editor">
            <el-input
              v-model="form.stepDraft"
              placeholder="输入一条处置步骤后回车添加"
              @keyup.enter="addStep"
            />
            <el-button @click="addStep">添加</el-button>
          </div>
        </el-form-item>
        <el-form-item label="步骤列表">
          <ol class="step-list">
            <li v-for="(s, i) in form.steps" :key="i">
              <span>{{ s }}</span>
              <el-button size="small" text type="danger" @click="removeStep(i)">删除</el-button>
            </li>
            <li v-if="form.steps.length === 0" class="muted">暂无步骤</li>
          </ol>
        </el-form-item>
        <el-divider>知识库链接</el-divider>
        <el-form-item label="新增链接">
          <div class="ref-editor">
            <el-input v-model="form.refTitle" placeholder="标题" style="width: 200px" />
            <el-input v-model="form.refUrl" placeholder="URL" style="width: 260px" />
            <el-button @click="addRef">添加</el-button>
          </div>
          <el-button class="kb-search-btn" @click="openKbSearch">🔍 从知识库检索关联链接</el-button>
        </el-form-item>
        <el-form-item label="链接列表">
          <ul class="ref-list">
            <li v-for="(r, i) in form.references" :key="i">
              <a :href="r.url" target="_blank" rel="noopener">{{ r.title || r.url }}</a>
              <el-button size="small" text type="danger" @click="removeRef(i)">删除</el-button>
            </li>
            <li v-if="form.references.length === 0" class="muted">暂无链接</li>
          </ul>
        </el-form-item>
        <el-divider>其他</el-divider>
        <el-form-item label="责任岗位">
          <el-input v-model="form.owner_role" placeholder="如：现场安全员" style="width: 100%" />
        </el-form-item>
        <el-form-item label="处置时限(分)">
          <el-input-number v-model="form.est_minutes as any" :min="0" :controls="false" placeholder="选填" style="width: 100%" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tags" placeholder="逗号分隔，如：围栏,侵入" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="kbDialogVisible"
      title="从知识库检索关联链接"
      width="640px"
      top="5vh"
    >
      <el-input
        v-model="kbQuery"
        placeholder="检索关键词：预案名称/要点/标签，或告警类型（如 fence_intrusion）"
        @keyup.enter="runKbSearch"
      >
        <template #append>
          <el-button @click="runKbSearch">检索</el-button>
        </template>
      </el-input>
      <div v-loading="kbLoading" class="kb-result">
        <el-empty
          v-if="!kbLoading && kbResults.length === 0"
          :image-size="50"
          description="无匹配知识库条目"
        />
        <div v-for="r in kbResults" :key="r.id" class="kb-item">
          <div class="kb-meta">
            <a :href="r.url" target="_blank" rel="noopener" class="kb-title">{{ r.title }}</a>
            <span class="kb-source">{{ r.source }}</span>
            <p class="kb-summary">{{ r.summary }}</p>
          </div>
          <el-button size="small" type="primary" @click="addKbOne(r)">添加</el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="kbDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.bar-actions { display: flex; gap: 8px; }
.title { font-size: 15px; font-weight: 600; color: #303133; }
.hint { margin-bottom: 12px; }
.filters { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.muted { color: #c0c4cc; font-size: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.step-editor, .ref-editor { display: flex; gap: 8px; width: 100%; }
.step-list, .ref-list { margin: 0; padding-left: 18px; }
.step-list li, .ref-list li { margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.kb-search-btn { margin-left: 8px; }
.kb-result { margin-top: 12px; max-height: 50vh; overflow-y: auto; }
.kb-item { display: flex; align-items: flex-start; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.kb-meta { flex: 1; min-width: 0; }
.kb-title { font-weight: 600; color: #303133; text-decoration: none; }
.kb-title:hover { color: #409eff; }
.kb-source { margin-left: 8px; font-size: 12px; color: #909399; background: #f4f4f5; padding: 1px 6px; border-radius: 4px; }
.kb-summary { margin: 4px 0 0; font-size: 12px; color: #606266; line-height: 1.5; }
</style>
