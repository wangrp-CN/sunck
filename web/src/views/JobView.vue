<script setup lang="ts">
/**
 * 作业计划管理 · 作业列表
 *
 * 对齐原型《作业列表 / 新增作业计划 / 查看作业计划 / 编辑作业计划》：
 * - 搜索区：项目名称、计划名称（左右模糊）、计划启动、计划状态 + 查询/重置/新增
 * - 列表区：默认创建时间倒序，超行省略 + hover 全文，操作 编辑/复制/查看/删除
 * - 三步向导：① 计划信息 ② 绑定人机设备（人员↔定位设备、大机六要素）
 *   ③ 绑定电子围栏并逐条定义规则（监控目标/触发条件/时间范围/停留时间）
 */
import { computed, onMounted, onBeforeUnmount, reactive, ref } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import { ArrowDown, Plus, Refresh, Search } from "@element-plus/icons-vue";
import {
  fetchJobs,
  fetchJob,
  createJob,
  updateJob,
  deleteJob,
  cloneJob,
  saveJobAsTemplate,
} from "@/api/job";
import { fetchProjects } from "@/api/project";
import { fetchPersons } from "@/api/person";
import { fetchMachines } from "@/api/machine";
import { fetchFences } from "@/api/fence";
import { fetchDevices } from "@/api/device";
import type {
  Project,
  Person,
  Machine,
  Fence,
  Device,
  WorkPlan,
  WorkPlanStatus,
  PersonBindingIn,
  MachineBindingIn,
  FenceRuleIn,
} from "@/types";
import { useAuthStore } from "@/stores/auth";
import TablePager from "@/components/TablePager.vue";

const auth = useAuthStore();
const canAdd = computed(() => auth.hasPermission("job:add"));
const canEdit = computed(() => auth.hasPermission("job:edit"));
const canDelete = computed(() => auth.hasPermission("job:delete"));

/* ============================ 字典 ============================ */

/** 计划状态：后端存储值 ↔ 原型展示值 */
const STATUS_OPTIONS: { value: WorkPlanStatus; label: string }[] = [
  { value: "草稿", label: "未开始" },
  { value: "执行中", label: "进行中" },
  { value: "已完成", label: "已结束" },
];
const STATUS_DISPLAY: Record<string, string> = Object.fromEntries(
  STATUS_OPTIONS.map((o) => [o.value, o.label]),
);

/** 计划启动 */
const START_OPTIONS = [
  { label: "启动", value: true },
  { label: "关闭", value: false },
];

/** 监控目标（原型第三步固定六选项） */
const MONITOR_TARGETS = [
  "计划内人员",
  "计划外人员",
  "计划内大机",
  "计划外大机",
  "计划内人员与大机",
  "计划外人员与大机",
];

/** 触发条件 */
const TRIGGER_CONDITIONS = ["进入", "离开"];

/** 设备类型 → 用途：人员定位 / 大机防侵限 / 车载语音报警 */
const DEV_LOCATE = "locate";
const DEV_MACHINE = "anti_intrusion";
const DEV_VOICE = "train_approach";

/* ============================ 列表 ============================ */

const projects = ref<Project[]>([]);
const list = ref<WorkPlan[]>([]);
const total = ref(0);
const loading = ref(false);
const loadError = ref("");

const filters = reactive({
  project_id: null as number | null,
  keyword: "",
  is_start: undefined as boolean | undefined,
  status: "" as string,
});

const page = ref(1);
const size = ref(10);
const sortBy = ref("created_at");
const sortOrder = ref<"asc" | "desc">("desc");

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* 项目下拉失败不阻断列表 */
  }
}

async function loadJobs() {
  loading.value = true;
  loadError.value = "";
  try {
    const res = await fetchJobs({
      project_id: filters.project_id ?? undefined,
      keyword: filters.keyword.trim() || undefined,
      is_start: filters.is_start,
      status: filters.status || undefined,
      sort_by: sortBy.value,
      order: sortOrder.value,
      page: page.value,
      size: size.value,
    });
    list.value = res.items;
    total.value = res.total;
  } catch (e: unknown) {
    list.value = [];
    total.value = 0;
    loadError.value = (e as Error)?.message || "加载作业计划失败，请稍后重试";
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.value = 1;
  loadJobs();
}

function resetFilters() {
  filters.project_id = null;
  filters.keyword = "";
  filters.is_start = undefined;
  filters.status = "";
  sortBy.value = "created_at";
  sortOrder.value = "desc";
  page.value = 1;
  loadJobs();
}

function handleSortChange(payload: { prop: string | null; order: string | null }) {
  if (!payload.prop || !payload.order) {
    sortBy.value = "created_at";
    sortOrder.value = "desc";
  } else {
    sortBy.value = payload.prop;
    sortOrder.value = payload.order === "ascending" ? "asc" : "desc";
  }
  page.value = 1;
  loadJobs();
}

function displayStatus(s: string): string {
  return STATUS_DISPLAY[s] || s;
}

function statusTagType(s: string): "primary" | "info" | "success" | "warning" {
  if (s === "执行中") return "warning";
  if (s === "已完成") return "success";
  return "info";
}

/** 计划时间展示：优先结构化时间窗，回退历史文本 */
function displayPlanTime(row: Partial<WorkPlan> | null): string {
  if (!row) return "-";
  const start = (row.plan_start || "").replace("T", " ");
  const end = (row.plan_end || "").replace("T", " ");
  if (start || end) return `${start || "-"} ~ ${end || "-"}`;
  return row.plan_time || "-";
}

/* ====================== 资源选项（三步向导用） ====================== */

const persons = ref<Person[]>([]);
const machines = ref<Machine[]>([]);
const fences = ref<Fence[]>([]);
const locateDevices = ref<Device[]>([]);
const machineDevices = ref<Device[]>([]);
const voiceDevices = ref<Device[]>([]);
const optionsLoaded = ref(false);

async function ensureOptions() {
  if (optionsLoaded.value) return;
  try {
    const [p, m, f, dl, dm, dv] = await Promise.all([
      fetchPersons({ page: 1, size: 500 }),
      fetchMachines({ page: 1, size: 500 }),
      fetchFences({ page: 1, size: 500 }),
      fetchDevices({ device_type: DEV_LOCATE, page: 1, size: 500 }),
      fetchDevices({ device_type: DEV_MACHINE, page: 1, size: 500 }),
      fetchDevices({ device_type: DEV_VOICE, page: 1, size: 500 }),
    ]);
    persons.value = p.items;
    machines.value = m.items;
    fences.value = f.items;
    locateDevices.value = dl.items;
    machineDevices.value = dm.items;
    voiceDevices.value = dv.items;
    optionsLoaded.value = true;
  } catch (e: unknown) {
    ElMessage.warning((e as Error)?.message || "资源选项加载失败，部分下拉可能为空");
  }
}

/** 按当前计划所属项目过滤候选资源（原型：可选项为当前项目下的资源） */
function scoped<T extends { project_id: number | null }>(items: T[]): T[] {
  if (form.project_id == null) return items;
  return items.filter((i) => i.project_id == null || i.project_id === form.project_id);
}
const personOptions = computed(() => scoped(persons.value));
const machineOptions = computed(() => scoped(machines.value));
const fenceOptions = computed(() => scoped(fences.value));
const locateOptions = computed(() => scoped(locateDevices.value));
const machineDevOptions = computed(() => scoped(machineDevices.value));
const voiceOptions = computed(() => scoped(voiceDevices.value));

function personNo(id?: number | null): string {
  return persons.value.find((x) => x.id === id)?.person_no || "-";
}
function personName(id?: number | null): string {
  return persons.value.find((x) => x.id === id)?.name || (id == null ? "-" : `#${id}`);
}
function machineLabel(id?: number | null): string {
  const m = machines.value.find((x) => x.id === id);
  return m ? `${m.machine_no}(${m.machine_type || "大机"})` : id == null ? "-" : `#${id}`;
}
function deviceName(no?: string | null): string {
  if (!no) return "-";
  const all = [...locateDevices.value, ...machineDevices.value, ...voiceDevices.value];
  return all.find((d) => d.device_no === no)?.name || no;
}
function fenceLabel(id?: number | null): string {
  return fences.value.find((x) => x.id === id)?.name || (id == null ? "-" : `#${id}`);
}

/* ============================ 三步向导 ============================ */

const wizardVisible = ref(false);
const wizardMode = ref<"create" | "edit">("create");
const activeStep = ref(0);
const saving = ref(false);
const step1Ref = ref<FormInstance>();

interface WizardForm {
  id?: number;
  project_id: number | null;
  name: string;
  is_start: boolean;
  description: string;
  plan_range: string[];
  status: WorkPlanStatus;
}

function emptyForm(): WizardForm {
  return {
    project_id: null,
    name: "",
    is_start: true, // 原型：计划启动默认「启动」
    description: "",
    plan_range: [],
    status: "草稿",
  };
}
const form = reactive<WizardForm>(emptyForm());

const step1Rules: FormRules = {
  project_id: [{ required: true, message: "请选择项目名称", trigger: "change" }],
  name: [
    { required: true, message: "请输入计划名称", trigger: "blur" },
    { max: 128, message: "计划名称不超过 128 个字符", trigger: "blur" },
  ],
  plan_range: [
    {
      required: true,
      validator: (_r: unknown, v: string[], cb: (e?: Error) => void) => {
        if (!v || v.length !== 2 || !v[0] || !v[1]) return cb(new Error("请选择计划时间"));
        if (v[0] >= v[1]) return cb(new Error("结束时间必须晚于开始时间"));
        cb();
      },
      trigger: "change",
    },
  ],
};

/* --- 第二步：人员及设备 --- */
const personRows = ref<PersonBindingIn[]>([]);
const personDraft = reactive<{ person_id: number | null; device_no: string | null }>({
  person_id: null,
  device_no: null,
});

function addPersonRow() {
  if (personDraft.person_id == null) {
    ElMessage.warning("请选择人员姓名");
    return;
  }
  if (!personDraft.device_no) {
    ElMessage.warning("请选择定位设备名称");
    return;
  }
  if (personRows.value.some((r) => r.person_id === personDraft.person_id)) {
    ElMessage.warning("该人员已在列表中");
    return;
  }
  if (personRows.value.some((r) => r.device_no === personDraft.device_no)) {
    ElMessage.warning("该定位设备已被其他人员占用");
    return;
  }
  personRows.value.push({
    person_id: personDraft.person_id,
    device_no: personDraft.device_no,
  });
  personDraft.person_id = null;
  personDraft.device_no = null;
}
function removePersonRow(idx: number) {
  personRows.value.splice(idx, 1);
}

/* --- 第二步：大型机械 --- */
const machineRows = ref<MachineBindingIn[]>([]);
function emptyMachineDraft(): MachineBindingIn {
  return {
    machine_id: 0,
    guard_person_id: null,
    driver_person_id: null,
    arm_device_no: null,
    body_device_no: null,
    voice_device_no: null,
  };
}
const machineDraft = reactive<MachineBindingIn>(emptyMachineDraft());

function addMachineRow() {
  if (!machineDraft.machine_id) {
    ElMessage.warning("请选择大机编号");
    return;
  }
  if (machineDraft.guard_person_id == null) {
    ElMessage.warning("请选择防护人员");
    return;
  }
  if (machineDraft.driver_person_id == null) {
    ElMessage.warning("请选择驾驶人员");
    return;
  }
  if (machineRows.value.some((r) => r.machine_id === machineDraft.machine_id)) {
    ElMessage.warning("该大机已在列表中");
    return;
  }
  machineRows.value.push({ ...machineDraft });
  Object.assign(machineDraft, emptyMachineDraft());
}
function removeMachineRow(idx: number) {
  machineRows.value.splice(idx, 1);
}

/* --- 第三步：电子围栏规则 --- */
const fenceRows = ref<FenceRuleIn[]>([]);
function emptyFenceDraft(): FenceRuleIn {
  return {
    fence_id: 0,
    monitor_target: null,
    trigger_condition: "进入",
    time_range: null,
    dwell_time: 0,
  };
}
const fenceDraft = reactive<FenceRuleIn>(emptyFenceDraft());
/** el-time-picker is-range 的绑定值：["08:00:00","12:00:00"] */
const fenceTimeRange = ref<string[]>([]);

function addFenceRow() {
  if (!fenceDraft.fence_id) {
    ElMessage.warning("请选择电子围栏");
    return;
  }
  if (!fenceDraft.monitor_target) {
    ElMessage.warning("请选择监控目标");
    return;
  }
  if (!fenceDraft.trigger_condition) {
    ElMessage.warning("请选择触发条件");
    return;
  }
  if (fenceRows.value.some((r) => r.fence_id === fenceDraft.fence_id)) {
    ElMessage.warning("该围栏已配置规则，请先删除后重新添加");
    return;
  }
  const tr = fenceTimeRange.value;
  fenceRows.value.push({
    ...fenceDraft,
    time_range: tr && tr.length === 2 ? `${tr[0]}~${tr[1]}` : null,
    dwell_time: fenceDraft.dwell_time ?? 0,
  });
  Object.assign(fenceDraft, emptyFenceDraft());
  fenceTimeRange.value = [];
}
function removeFenceRow(idx: number) {
  fenceRows.value.splice(idx, 1);
}

/* --- 打开 / 步骤流转 / 提交 --- */

function resetWizardState() {
  Object.assign(form, emptyForm());
  personRows.value = [];
  machineRows.value = [];
  fenceRows.value = [];
  Object.assign(personDraft, { person_id: null, device_no: null });
  Object.assign(machineDraft, emptyMachineDraft());
  Object.assign(fenceDraft, emptyFenceDraft());
  fenceTimeRange.value = [];
  activeStep.value = 0;
  step1Ref.value?.clearValidate();
}

async function openCreate() {
  wizardMode.value = "create";
  resetWizardState();
  // 默认沿用列表已筛选的项目（原型：默认为列表页选中的项目）
  form.project_id = filters.project_id;
  wizardVisible.value = true;
  await ensureOptions();
}

async function openEdit(row: WorkPlan) {
  wizardMode.value = "edit";
  resetWizardState();
  await ensureOptions();
  try {
    const d = await fetchJob(row.id);
    Object.assign(form, {
      id: d.id,
      project_id: d.project_id ?? null,
      name: d.name,
      is_start: d.is_start,
      description: d.description ?? "",
      plan_range: d.plan_start && d.plan_end ? [d.plan_start, d.plan_end] : [],
      status: d.status,
    });
    personRows.value = (d.person_bindings || []).map((b) => ({
      person_id: b.person_id,
      device_no: b.device_no ?? null,
    }));
    machineRows.value = (d.machine_bindings || []).map((b) => ({
      machine_id: b.machine_id,
      guard_person_id: b.guard_person_id ?? null,
      driver_person_id: b.driver_person_id ?? null,
      arm_device_no: b.arm_device_no ?? null,
      body_device_no: b.body_device_no ?? null,
      voice_device_no: b.voice_device_no ?? null,
    }));
    fenceRows.value = (d.fence_rules || []).map((r) => ({
      fence_id: r.fence_id,
      monitor_target: r.monitor_target ?? null,
      trigger_condition: r.trigger_condition ?? null,
      time_range: r.time_range ?? null,
      dwell_time: r.dwell_time ?? 0,
    }));
    wizardVisible.value = true;
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || "加载计划详情失败");
  }
}

async function nextStep() {
  if (activeStep.value === 0) {
    const ok = await step1Ref.value?.validate().catch(() => false);
    if (!ok) return;
  }
  if (activeStep.value === 1 && personRows.value.length === 0 && machineRows.value.length === 0) {
    ElMessage.warning("请至少绑定一条人员或大型机械记录");
    return;
  }
  if (activeStep.value < 2) activeStep.value += 1;
}

function buildRequest() {
  const [start, end] = form.plan_range;
  return {
    project_id: form.project_id,
    name: form.name.trim(),
    is_start: form.is_start,
    description: form.description.trim() || null,
    plan_time: start && end ? `${start.replace("T", " ")}~${end.replace("T", " ")}` : null,
    plan_start: start || null,
    plan_end: end || null,
    status: form.status,
    person_bindings: personRows.value,
    machine_bindings: machineRows.value,
    fence_rules: fenceRows.value,
  };
}

async function submitWizard() {
  if (fenceRows.value.length === 0) {
    try {
      await ElMessageBox.confirm(
        "尚未绑定任何电子围栏规则，保存后该计划不会产生围栏告警。是否继续？",
        "提示",
        { type: "warning", confirmButtonText: "继续保存", cancelButtonText: "返回补充" },
      );
    } catch {
      return;
    }
  }
  saving.value = true;
  try {
    const req = buildRequest();
    if (wizardMode.value === "create") {
      await createJob(req);
      ElMessage.success("作业计划已创建");
    } else {
      await updateJob(form.id!, req);
      ElMessage.success("作业计划已更新");
    }
    wizardVisible.value = false;
    loadJobs();
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

/* ============================ 查看 / 复制 / 删除 ============================ */

const detailVisible = ref(false);
const detailLoading = ref(false);
const detail = ref<WorkPlan | null>(null);

async function openDetail(row: WorkPlan) {
  detail.value = null;
  detailVisible.value = true;
  detailLoading.value = true;
  await ensureOptions();
  try {
    detail.value = await fetchJob(row.id);
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || "加载计划详情失败");
    detailVisible.value = false;
  } finally {
    detailLoading.value = false;
  }
}

/** 复制：按原型「复制一条相同计划并进入编辑」 */
async function handleClone(row: WorkPlan) {
  try {
    const created = await cloneJob(row.id);
    ElMessage.success("已复制计划，请继续编辑");
    await loadJobs();
    await openEdit(created);
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || "复制失败");
  }
}

async function handleSaveTemplate(row: WorkPlan) {
  try {
    await saveJobAsTemplate(row.id);
    ElMessage.success("已存为模板");
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || "存为模板失败");
  }
}

async function handleDelete(row: WorkPlan) {
  try {
    await ElMessageBox.confirm("您确认删除当前作业计划？", "删除确认", {
      type: "warning",
      confirmButtonText: "确定删除",
      cancelButtonText: "取消",
      confirmButtonClass: "el-button--danger",
    });
  } catch {
    return;
  }
  try {
    await deleteJob(row.id);
    ElMessage.success("作业计划已删除");
    // 删掉当前页最后一条时回退一页，避免停留空页
    if (list.value.length === 1 && page.value > 1) page.value -= 1;
    loadJobs();
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || "删除失败");
  }
}

function handleCommand(cmd: string, row: WorkPlan) {
  if (cmd === "clone") handleClone(row);
  else if (cmd === "template") handleSaveTemplate(row);
  else if (cmd === "delete") handleDelete(row);
}

/* ============================ 响应式 ============================ */

const viewportWidth = ref(typeof window === "undefined" ? 1440 : window.innerWidth);
function onResize() {
  viewportWidth.value = window.innerWidth;
}
const isNarrow = computed(() => viewportWidth.value < 1024);
const dialogWidth = computed(() => (viewportWidth.value < 1100 ? "94vw" : "1040px"));
const detailWidth = computed(() => (viewportWidth.value < 960 ? "94vw" : "900px"));
const filterItemWidth = computed(() => (isNarrow.value ? "100%" : "200px"));

onMounted(async () => {
  window.addEventListener("resize", onResize);
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* 未登录由路由守卫处理 */
    }
  }
  await loadProjects();
  await loadJobs();
});

onBeforeUnmount(() => window.removeEventListener("resize", onResize));
</script>

<template>
  <div class="job-page">
    <!-- ==================== 搜索区 ==================== -->
    <el-card shadow="never" class="filter-card">
      <el-form :inline="!isNarrow" class="filter-form" @submit.prevent>
        <el-form-item label="项目名称">
          <el-select
            v-model="filters.project_id"
            placeholder="全部"
            clearable
            filterable
            :style="{ width: filterItemWidth }"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划名称">
          <el-input
            v-model="filters.keyword"
            placeholder="请输入计划名称"
            clearable
            :style="{ width: filterItemWidth }"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="计划启动">
          <el-select
            v-model="filters.is_start"
            placeholder="全部"
            clearable
            :style="{ width: filterItemWidth }"
          >
            <el-option
              v-for="o in START_OPTIONS"
              :key="String(o.value)"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="计划状态">
          <el-select
            v-model="filters.status"
            placeholder="全部"
            clearable
            :style="{ width: filterItemWidth }"
          >
            <el-option
              v-for="s in STATUS_OPTIONS"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item class="filter-ops">
          <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
          <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
          <el-button v-if="canAdd" type="primary" :icon="Plus" @click="openCreate">
            新增
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- ==================== 列表区 ==================== -->
    <el-card shadow="never" class="table-card">
      <el-alert
        v-if="loadError"
        class="load-error"
        type="error"
        :title="loadError"
        show-icon
        :closable="false"
      >
        <template #default>
          <div class="err-line">
            <span>{{ loadError }}</span>
            <el-button link type="primary" @click="loadJobs">重试</el-button>
          </div>
        </template>
      </el-alert>

      <el-table
        v-loading="loading"
        :data="list"
        border
        stripe
        row-key="id"
        class="job-table"
        :default-sort="{ prop: 'created_at', order: 'descending' }"
        @sort-change="handleSortChange"
      >
        <el-table-column label="序号" type="index" width="64" align="center" :index="(i: number) => (page - 1) * size + i + 1" />
        <el-table-column label="项目名称" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.project_name || "-" }}</template>
        </el-table-column>
        <el-table-column
          label="计划名称"
          prop="name"
          min-width="180"
          sortable="custom"
          show-overflow-tooltip
        />
        <el-table-column label="计划启动" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_start ? 'success' : 'info'" size="small" effect="light">
              {{ row.is_start ? "启动" : "关闭" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="计划说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || "-" }}</template>
        </el-table-column>
        <el-table-column
          label="计划时间"
          prop="plan_start"
          min-width="210"
          sortable="custom"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ displayPlanTime(row) }}</template>
        </el-table-column>
        <el-table-column label="计划状态" prop="status" width="110" align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="light">
              {{ displayStatus(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="创建时间"
          prop="created_at"
          width="180"
          sortable="custom"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ row.created_at || "-" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button v-if="canEdit" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-dropdown
              v-if="canAdd || canDelete"
              trigger="click"
              @command="(c: string) => handleCommand(c, row)"
            >
              <el-button link type="primary">
                更多<el-icon class="more-icon"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="canAdd" command="clone">复制</el-dropdown-item>
                  <el-dropdown-item v-if="canAdd" command="template">存为模板</el-dropdown-item>
                  <el-dropdown-item v-if="canDelete" command="delete" divided>
                    <span class="danger-text">删除</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="loadError ? '数据加载失败' : '暂无作业计划'" :image-size="90" />
        </template>
      </el-table>

      <TablePager v-model:page="page" v-model:size="size" :total="total" @change="loadJobs" />
    </el-card>

    <!-- ==================== 三步向导 ==================== -->
    <el-dialog
      v-model="wizardVisible"
      :title="wizardMode === 'create' ? '新增作业计划' : '编辑作业计划'"
      :width="dialogWidth"
      top="6vh"
      destroy-on-close
      :close-on-click-modal="false"
    >
      <el-steps :active="activeStep" finish-status="success" align-center class="wizard-steps">
        <el-step title="计划信息" />
        <el-step title="绑定人机设备" />
        <el-step title="绑定电子围栏" />
      </el-steps>

      <div class="step-body">
        <!-- 第一步 -->
        <el-form
          v-show="activeStep === 0"
          ref="step1Ref"
          :model="form"
          :rules="step1Rules"
          label-width="100px"
          class="step1-form"
        >
          <el-form-item label="项目名称" prop="project_id">
            <el-select v-model="form.project_id" placeholder="请选择项目" filterable clearable>
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="计划名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入计划名称" maxlength="128" show-word-limit />
          </el-form-item>
          <el-form-item label="计划启动" prop="is_start">
            <el-select v-model="form.is_start">
              <el-option v-for="o in START_OPTIONS" :key="String(o.value)" :label="o.label" :value="o.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="计划说明" prop="description">
            <el-input
              v-model="form.description"
              type="textarea"
              :rows="4"
              maxlength="1024"
              show-word-limit
              placeholder="请输入计划说明（选填）"
            />
          </el-form-item>
          <el-form-item label="计划时间" prop="plan_range">
            <el-date-picker
              v-model="form.plan_range"
              type="datetimerange"
              range-separator="~"
              start-placeholder="计划开始时间"
              end-placeholder="计划结束时间"
              value-format="YYYY-MM-DDTHH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              style="width: 100%"
            />
          </el-form-item>
        </el-form>

        <!-- 第二步 -->
        <div v-show="activeStep === 1" class="step2">
          <div class="sub-title">人员及设备</div>
          <div class="draft-row">
            <div class="draft-field">
              <label class="req">人员姓名</label>
              <el-select v-model="personDraft.person_id" filterable clearable placeholder="请选择人员">
                <el-option
                  v-for="p in personOptions"
                  :key="p.id"
                  :label="`${p.name}（${p.person_no}）`"
                  :value="p.id"
                />
              </el-select>
            </div>
            <div class="draft-field">
              <label class="req">定位设备名称</label>
              <el-select v-model="personDraft.device_no" filterable clearable placeholder="请选择定位设备">
                <el-option
                  v-for="d in locateOptions"
                  :key="d.device_no"
                  :label="`${d.name}（${d.device_no}）`"
                  :value="d.device_no"
                />
              </el-select>
            </div>
            <el-button type="primary" plain :icon="Plus" @click="addPersonRow">添加人员及设备</el-button>
          </div>
          <el-table :data="personRows" border size="small" class="bind-table">
            <el-table-column label="人员姓名" min-width="120">
              <template #default="{ row }">{{ personName(row.person_id) }}</template>
            </el-table-column>
            <el-table-column label="人员编号" min-width="110">
              <template #default="{ row }">{{ personNo(row.person_id) }}</template>
            </el-table-column>
            <el-table-column label="定位设备名" min-width="140">
              <template #default="{ row }">{{ deviceName(row.device_no) }}</template>
            </el-table-column>
            <el-table-column label="设备编号" min-width="120">
              <template #default="{ row }">{{ row.device_no || "-" }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ $index }">
                <el-button link type="danger" @click="removePersonRow($index)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><span class="empty-hint">尚未添加人员</span></template>
          </el-table>

          <div class="sub-title mt">大型机械</div>
          <div class="draft-grid">
            <div class="draft-field">
              <label class="req">大机编号</label>
              <el-select v-model="machineDraft.machine_id" filterable clearable placeholder="请选择大机">
                <el-option
                  v-for="m in machineOptions"
                  :key="m.id"
                  :label="`${m.machine_no}(${m.machine_type || '大机'})`"
                  :value="m.id"
                />
              </el-select>
            </div>
            <div class="draft-field">
              <label class="req">防护人员</label>
              <el-select v-model="machineDraft.guard_person_id" filterable clearable placeholder="请选择防护人员">
                <el-option
                  v-for="p in personOptions"
                  :key="p.id"
                  :label="`${p.name}（${p.person_no}）`"
                  :value="p.id"
                />
              </el-select>
            </div>
            <div class="draft-field">
              <label class="req">驾驶人员</label>
              <el-select v-model="machineDraft.driver_person_id" filterable clearable placeholder="请选择驾驶人员">
                <el-option
                  v-for="p in personOptions"
                  :key="p.id"
                  :label="`${p.name}（${p.person_no}）`"
                  :value="p.id"
                />
              </el-select>
            </div>
            <div class="draft-field">
              <label>大机前臂定位设备</label>
              <el-select v-model="machineDraft.arm_device_no" filterable clearable placeholder="选填">
                <el-option
                  v-for="d in machineDevOptions"
                  :key="d.device_no"
                  :label="`${d.name}（${d.device_no}）`"
                  :value="d.device_no"
                />
              </el-select>
            </div>
            <div class="draft-field">
              <label>大机机身定位设备</label>
              <el-select v-model="machineDraft.body_device_no" filterable clearable placeholder="选填">
                <el-option
                  v-for="d in machineDevOptions"
                  :key="d.device_no"
                  :label="`${d.name}（${d.device_no}）`"
                  :value="d.device_no"
                />
              </el-select>
            </div>
            <div class="draft-field">
              <label>车载语音设备</label>
              <el-select v-model="machineDraft.voice_device_no" filterable clearable placeholder="选填">
                <el-option
                  v-for="d in voiceOptions"
                  :key="d.device_no"
                  :label="`${d.name}（${d.device_no}）`"
                  :value="d.device_no"
                />
              </el-select>
            </div>
          </div>
          <div class="draft-actions">
            <el-button type="primary" plain :icon="Plus" @click="addMachineRow">添加大型机械</el-button>
          </div>
          <el-table :data="machineRows" border size="small" class="bind-table">
            <el-table-column label="大机编号(大机类型)" min-width="150">
              <template #default="{ row }">{{ machineLabel(row.machine_id) }}</template>
            </el-table-column>
            <el-table-column label="防护人员" min-width="110">
              <template #default="{ row }">{{ personName(row.guard_person_id) }}</template>
            </el-table-column>
            <el-table-column label="驾驶人员" min-width="110">
              <template #default="{ row }">{{ personName(row.driver_person_id) }}</template>
            </el-table-column>
            <el-table-column label="大机前臂定位设备" min-width="140">
              <template #default="{ row }">{{ deviceName(row.arm_device_no) }}</template>
            </el-table-column>
            <el-table-column label="大机机身定位设备" min-width="140">
              <template #default="{ row }">{{ deviceName(row.body_device_no) }}</template>
            </el-table-column>
            <el-table-column label="车载语音设备" min-width="130">
              <template #default="{ row }">{{ deviceName(row.voice_device_no) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center" fixed="right">
              <template #default="{ $index }">
                <el-button link type="danger" @click="removeMachineRow($index)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><span class="empty-hint">尚未添加大型机械</span></template>
          </el-table>
        </div>

        <!-- 第三步 -->
        <div v-show="activeStep === 2" class="step3">
          <div class="sub-title">电子围栏与告警规则</div>
          <div class="draft-grid">
            <div class="draft-field">
              <label class="req">电子围栏</label>
              <el-select v-model="fenceDraft.fence_id" filterable clearable placeholder="请选择围栏">
                <el-option v-for="f in fenceOptions" :key="f.id" :label="f.name" :value="f.id" />
              </el-select>
            </div>
            <div class="draft-field">
              <label class="req">监控目标</label>
              <el-select v-model="fenceDraft.monitor_target" clearable placeholder="请选择监控目标">
                <el-option v-for="t in MONITOR_TARGETS" :key="t" :label="t" :value="t" />
              </el-select>
            </div>
            <div class="draft-field">
              <label class="req">触发条件</label>
              <el-select v-model="fenceDraft.trigger_condition" clearable placeholder="请选择触发条件">
                <el-option v-for="c in TRIGGER_CONDITIONS" :key="c" :label="c" :value="c" />
              </el-select>
            </div>
            <div class="draft-field">
              <label>时间范围</label>
              <el-time-picker
                v-model="fenceTimeRange"
                is-range
                range-separator="~"
                start-placeholder="开始"
                end-placeholder="结束"
                value-format="HH:mm:ss"
                style="width: 100%"
              />
            </div>
            <div class="draft-field">
              <label>停留时间(s)</label>
              <el-input-number
                v-model="fenceDraft.dwell_time"
                :min="0"
                :max="86400"
                controls-position="right"
                style="width: 100%"
              />
            </div>
          </div>
          <div class="draft-actions">
            <el-button type="primary" plain :icon="Plus" @click="addFenceRow">添加电子围栏</el-button>
          </div>
          <el-table :data="fenceRows" border size="small" class="bind-table">
            <el-table-column label="电子围栏" min-width="160">
              <template #default="{ row }">{{ fenceLabel(row.fence_id) }}</template>
            </el-table-column>
            <el-table-column label="监控目标" min-width="140">
              <template #default="{ row }">{{ row.monitor_target || "-" }}</template>
            </el-table-column>
            <el-table-column label="触发条件" width="100" align="center">
              <template #default="{ row }">{{ row.trigger_condition || "-" }}</template>
            </el-table-column>
            <el-table-column label="时间范围" min-width="170">
              <template #default="{ row }">{{ row.time_range || "全天" }}</template>
            </el-table-column>
            <el-table-column label="停留时间(s)" width="110" align="center">
              <template #default="{ row }">{{ row.dwell_time ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ $index }">
                <el-button link type="danger" @click="removeFenceRow($index)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><span class="empty-hint">尚未添加电子围栏规则</span></template>
          </el-table>
        </div>
      </div>

      <template #footer>
        <el-button @click="wizardVisible = false">返回</el-button>
        <el-button v-if="activeStep > 0" @click="activeStep -= 1">上一步</el-button>
        <el-button v-if="activeStep < 2" type="primary" @click="nextStep">下一步</el-button>
        <el-button v-else type="primary" :loading="saving" @click="submitWizard">确认</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 查看详情 ==================== -->
    <el-dialog v-model="detailVisible" title="查看作业计划" :width="detailWidth" top="6vh">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="detail">
          <div class="sub-title">计划信息</div>
          <el-descriptions :column="isNarrow ? 1 : 2" border size="default">
            <el-descriptions-item label="项目名称">{{ detail.project_name || "-" }}</el-descriptions-item>
            <el-descriptions-item label="计划名称">{{ detail.name }}</el-descriptions-item>
            <el-descriptions-item label="计划启动">
              <el-tag :type="detail.is_start ? 'success' : 'info'" size="small">
                {{ detail.is_start ? "启动" : "关闭" }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="计划状态">
              <el-tag :type="statusTagType(detail.status)" size="small">
                {{ displayStatus(detail.status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="计划时间" :span="2">
              {{ displayPlanTime(detail) }}
            </el-descriptions-item>
            <el-descriptions-item label="计划说明" :span="2">
              {{ detail.description || "-" }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间" :span="2">
              {{ detail.created_at || "-" }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="sub-title mt">人员及设备</div>
          <el-table :data="detail.person_bindings || []" border size="small">
            <el-table-column label="人员姓名" min-width="110">
              <template #default="{ row }">{{ row.person_name || personName(row.person_id) }}</template>
            </el-table-column>
            <el-table-column label="人员编号" min-width="110">
              <template #default="{ row }">{{ row.person_no || "-" }}</template>
            </el-table-column>
            <el-table-column label="定位设备名" min-width="140">
              <template #default="{ row }">{{ row.device_name || deviceName(row.device_no) }}</template>
            </el-table-column>
            <el-table-column label="设备编号" min-width="120">
              <template #default="{ row }">{{ row.device_no || "-" }}</template>
            </el-table-column>
            <template #empty><span class="empty-hint">未绑定人员</span></template>
          </el-table>

          <div class="sub-title mt">大型机械</div>
          <el-table :data="detail.machine_bindings || []" border size="small">
            <el-table-column label="大机编号(大机类型)" min-width="150">
              <template #default="{ row }">
                {{ row.machine_no ? `${row.machine_no}(${row.machine_type || "大机"})` : machineLabel(row.machine_id) }}
              </template>
            </el-table-column>
            <el-table-column label="防护人员" min-width="100">
              <template #default="{ row }">{{ row.guard_person_name || "-" }}</template>
            </el-table-column>
            <el-table-column label="驾驶人员" min-width="100">
              <template #default="{ row }">{{ row.driver_person_name || "-" }}</template>
            </el-table-column>
            <el-table-column label="大机前臂定位设备" min-width="140">
              <template #default="{ row }">{{ row.arm_device_name || row.arm_device_no || "-" }}</template>
            </el-table-column>
            <el-table-column label="大机机身定位设备" min-width="140">
              <template #default="{ row }">{{ row.body_device_name || row.body_device_no || "-" }}</template>
            </el-table-column>
            <el-table-column label="车载语音设备" min-width="130">
              <template #default="{ row }">{{ row.voice_device_name || row.voice_device_no || "-" }}</template>
            </el-table-column>
            <template #empty><span class="empty-hint">未绑定大型机械</span></template>
          </el-table>

          <div class="sub-title mt">电子围栏与告警规则</div>
          <el-table :data="detail.fence_rules || []" border size="small">
            <el-table-column label="电子围栏" min-width="160">
              <template #default="{ row }">{{ row.fence_name || fenceLabel(row.fence_id) }}</template>
            </el-table-column>
            <el-table-column label="监控目标" min-width="140">
              <template #default="{ row }">{{ row.monitor_target || "-" }}</template>
            </el-table-column>
            <el-table-column label="触发条件" width="100" align="center">
              <template #default="{ row }">{{ row.trigger_condition || "-" }}</template>
            </el-table-column>
            <el-table-column label="时间范围" min-width="170">
              <template #default="{ row }">{{ row.time_range || "全天" }}</template>
            </el-table-column>
            <el-table-column label="停留时间(s)" width="110" align="center">
              <template #default="{ row }">{{ row.dwell_time ?? 0 }}</template>
            </el-table-column>
            <template #empty><span class="empty-hint">未绑定电子围栏</span></template>
          </el-table>
        </template>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.job-page {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ---------- 搜索区 ---------- */
.filter-card :deep(.el-card__body) {
  padding: 16px 16px 2px;
}
.filter-form {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0 4px;
}
.filter-form :deep(.el-form-item) {
  margin-right: 18px;
  margin-bottom: 14px;
}
.filter-ops {
  margin-left: auto;
  margin-right: 0 !important;
}

/* ---------- 列表区 ---------- */
.table-card :deep(.el-card__body) {
  padding: 12px 16px 4px;
}
.load-error {
  margin-bottom: 10px;
}
.err-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.job-table {
  width: 100%;
}
.more-icon {
  margin-left: 2px;
  vertical-align: middle;
}
.danger-text {
  color: var(--el-color-danger);
}

/* ---------- 向导 ---------- */
.wizard-steps {
  margin-bottom: 6px;
}
.step-body {
  padding: 18px 4px 4px;
  min-height: 320px;
  max-height: 64vh;
  overflow-y: auto;
}
.step1-form {
  max-width: 720px;
}
.step1-form :deep(.el-select),
.step1-form :deep(.el-input) {
  width: 100%;
}
.sub-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  border-left: 3px solid var(--el-color-primary);
  padding-left: 8px;
  margin-bottom: 10px;
}
.sub-title.mt {
  margin-top: 22px;
}
.draft-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 12px;
}
.draft-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px 16px;
  margin-bottom: 12px;
}
.draft-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 220px;
  flex: 1 1 220px;
}
.draft-field label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.draft-field label.req::before {
  content: "*";
  color: var(--el-color-danger);
  margin-right: 4px;
}
.draft-field :deep(.el-select) {
  width: 100%;
}
.draft-actions {
  margin-bottom: 12px;
}
.bind-table {
  width: 100%;
}
.empty-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

/* ---------- 详情 ---------- */
.detail-body {
  min-height: 160px;
  max-height: 66vh;
  overflow-y: auto;
  padding-right: 4px;
}

/* ---------- 窄屏适配 ---------- */
@media (max-width: 1024px) {
  .job-page {
    padding: 10px;
  }
  .filter-ops {
    margin-left: 0;
  }
  .filter-form :deep(.el-form-item) {
    margin-right: 0;
    width: 100%;
  }
  .draft-grid {
    grid-template-columns: 1fr;
  }
  .draft-field {
    min-width: 0;
  }
}
</style>
