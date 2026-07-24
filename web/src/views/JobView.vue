<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { fetchJobs, fetchJob, createJob, updateJob, deleteJob, startJob, completeJob, cloneJob, saveJobAsTemplate } from "@/api/job";
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
  WorkPlanRule,
  WorkPlanStatus,
} from "@/types";
import { DEVICE_TYPE_LABELS } from "@/api/realtime";
import { useAuthStore } from "@/stores/auth";
import AttachmentManager from "@/components/AttachmentManager.vue";
import WorkPlanGantt from "@/components/WorkPlanGantt.vue";

const auth = useAuthStore();
const canAdd = computed(() => auth.user?.permission_codes.includes("job:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("job:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("job:delete") ?? false);

const STATUS_OPTIONS = ["草稿", "执行中", "已完成"];

const projects = ref<Project[]>([]);
const list = ref<WorkPlan[]>([]);
const total = ref(0);
const loading = ref(false);
const filters = reactive({
  keyword: "",
  project_id: null as number | null,
  status: "" as string,
  is_template: false,
});

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* 忽略 */
  }
}

// 甘特视图：加载全量（跟随项目筛选），用于时间窗总览
const ganttPlans = ref<WorkPlan[]>([]);
async function loadGanttPlans() {
  try {
    const res = await fetchJobs({
      project_id: filters.project_id ?? undefined,
      is_template: false,
      size: 1000,
    });
    ganttPlans.value = res.items;
  } catch {
    /* 忽略 */
  }
}

async function loadJobs() {
  loading.value = true;
  try {
    const res = await fetchJobs({
      keyword: filters.keyword || undefined,
      project_id: filters.project_id ?? undefined,
      status: filters.status || undefined,
      is_template: filters.is_template,
    });
    list.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载作业计划失败");
  } finally {
    loading.value = false;
  }
  void loadGanttPlans();
}

function resetFilters() {
  filters.keyword = "";
  filters.project_id = null;
  filters.status = "";
  filters.is_template = false;
  loadJobs();
}

// ===================== 三步式向导 =====================
const wizardVisible = ref(false);
const wizardMode = ref<"create" | "edit">("create");
const activeStep = ref(0);
const saving = ref(false);
const persons = ref<Person[]>([]);
const machines = ref<Machine[]>([]);
const devices = ref<Device[]>([]);
const fences = ref<Fence[]>([]);
const deviceValues = ref<string[]>([]);

interface WizardForm {
  id?: number;
  project_id: number | null;
  name: string;
  is_start: boolean;
  description: string | null;
  plan_time: string | null;
  plan_start: string | null;
  plan_end: string | null;
  status: WorkPlanStatus;
  rule: WorkPlanRule;
  person_ids: number[];
  machine_ids: number[];
  device_bindings: { device_type: string; device_no: string }[];
  fence_ids: number[];
}
const form = reactive<WizardForm>({
  project_id: null,
  name: "",
  is_start: false,
  description: null,
  plan_time: null,
  plan_start: null,
  plan_end: null,
  status: "草稿",
  rule: {
    monitor_target: null,
    trigger_condition: null,
    trigger_conditions: [],
    time_range: null,
    dwell_time: null,
  },
  person_ids: [],
  machine_ids: [],
  device_bindings: [],
  fence_ids: [],
});

function deviceOptionLabel(d: Device): string {
  const t = DEVICE_TYPE_LABELS[d.device_type as keyof typeof DEVICE_TYPE_LABELS] || d.device_type;
  return `${d.name}（${t}·${d.device_no}）`;
}

async function openCreate() {
  wizardMode.value = "create";
  activeStep.value = 0;
  Object.assign(form, {
    id: undefined,
    project_id: null,
    name: "",
    is_start: false,
    description: null,
    plan_time: null,
    plan_start: null,
    plan_end: null,
    status: "草稿",
    rule: {
      monitor_target: null,
      trigger_condition: null,
      trigger_conditions: [],
      time_range: null,
      dwell_time: null,
    },
    person_ids: [],
    machine_ids: [],
    device_bindings: [],
    fence_ids: [],
  });
  deviceValues.value = [];
  await ensureOptions();
  wizardVisible.value = true;
}

async function openEdit(row: WorkPlan) {
  wizardMode.value = "edit";
  activeStep.value = 0;
  try {
    const detail = await fetchJob(row.id);
    Object.assign(form, {
      id: detail.id,
      project_id: detail.project_id ?? null,
      name: detail.name,
      is_start: detail.is_start,
      description: detail.description ?? null,
      plan_time: detail.plan_time ?? null,
      plan_start: detail.plan_start ?? null,
      plan_end: detail.plan_end ?? null,
      status: detail.status,
      rule: detail.rule
        ? {
            monitor_target: detail.rule.monitor_target ?? null,
            trigger_condition: detail.rule.trigger_condition ?? null,
            trigger_conditions: detail.rule.trigger_conditions || [],
            time_range: detail.rule.time_range ?? null,
            dwell_time: detail.rule.dwell_time ?? null,
          }
        : {
            monitor_target: null,
            trigger_condition: null,
            trigger_conditions: [],
            time_range: null,
            dwell_time: null,
          },
      person_ids: (detail.persons || []).map((p) => p.id),
      machine_ids: (detail.machines || []).map((m) => m.id),
      device_bindings: (detail.devices || []).map((d) => ({
        device_type: d.device_type,
        device_no: d.device_no,
      })),
      fence_ids: (detail.fences || []).map((f) => f.id),
    });
    deviceValues.value = (detail.devices || []).map(
      (d) => `${d.device_type}::${d.device_no}`,
    );
  } catch (e: any) {
    ElMessage.error(e?.message || "加载详情失败");
    return;
  }
  await ensureOptions();
  wizardVisible.value = true;
}

async function ensureOptions() {
  try {
    const [p, m, d, f] = await Promise.all([
      fetchPersons({ page: 1, size: 500 }),
      fetchMachines({ page: 1, size: 500 }),
      fetchDevices({ page: 1, size: 500 }),
      fetchFences({ page: 1, size: 500 }),
    ]);
    persons.value = p.items;
    machines.value = m.items;
    devices.value = d.items;
    fences.value = f.items;
  } catch {
    /* 忽略 */
  }
}

function nextStep() {
  if (activeStep.value === 0 && !form.name) {
    ElMessage.warning("请填写计划名称");
    return;
  }
  if (activeStep.value < 2) activeStep.value += 1;
}

function buildRequest() {
  const device_bindings = deviceValues.value.map((v) => {
    const [device_type, device_no] = v.split("::");
    return { device_type, device_no };
  });
  return {
    project_id: form.project_id,
    name: form.name,
    is_start: form.is_start,
    description: form.description || null,
    plan_time: form.plan_time || null,
    plan_start: form.plan_start || null,
    plan_end: form.plan_end || null,
    status: form.status,
    rule: form.rule,
    person_ids: form.person_ids,
    machine_ids: form.machine_ids,
    device_bindings,
    fence_ids: form.fence_ids,
  };
}

async function submitWizard() {
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
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

// ===================== 详情 / 删除 =====================
const detailVisible = ref(false);
const detail = ref<WorkPlan | null>(null);
async function openDetail(row: WorkPlan) {
  try {
    detail.value = await fetchJob(row.id);
    detailVisible.value = true;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载详情失败");
  }
}

async function handleDelete(row: WorkPlan) {
  try {
    await ElMessageBox.confirm(
      `确认删除作业计划「${row.name}」？`,
      "提示",
      { type: "warning" },
    );
  } catch {
    return;
  }
  try {
    await deleteJob(row.id);
    ElMessage.success("已删除");
    loadJobs();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

async function startPlan(row: WorkPlan) {
  try {
    await startJob(row.id);
    ElMessage.success("作业计划已启动，规则引擎开始判定");
    loadJobs();
  } catch (e: any) {
    ElMessage.error(e?.message || "启动失败");
  }
}

async function completePlan(row: WorkPlan) {
  try {
    await completeJob(row.id);
    ElMessage.success("作业计划已标记完成，停止判定");
    loadJobs();
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

// 克隆为副本（深拷贝绑定，执行态清零）
async function clonePlan(row: WorkPlan) {
  try {
    await cloneJob(row.id);
    ElMessage.success("已克隆为副本（草稿/未激活）");
    loadJobs();
  } catch (e: any) {
    ElMessage.error(e?.message || "克隆失败");
  }
}

// 存为模板（深拷贝绑定，标记 is_template=true）
async function saveTemplate(row: WorkPlan) {
  if (row.is_template) {
    ElMessage.info("该计划已是模板");
    return;
  }
  try {
    await saveJobAsTemplate(row.id);
    ElMessage.success("已存为模板，可在模板库中复用");
    loadJobs();
  } catch (e: any) {
    ElMessage.error(e?.message || "存为模板失败");
  }
}

function statusTag(s: string): "" | "info" | "success" | "warning" {
  if (s === "执行中") return "warning";
  if (s === "已完成") return "success";
  if (s === "草稿") return "info";
  return "";
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* 忽略 */
    }
  }
  await loadProjects();
  await loadJobs();
  await loadGanttPlans();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <el-form :inline="true" class="filters">
        <el-form-item label="名称">
          <el-input
            v-model="filters.keyword"
            placeholder="计划名称"
            clearable
            style="width: 160px"
            @keyup.enter="loadJobs"
          />
        </el-form-item>
        <el-form-item label="项目">
          <el-select
            v-model="filters.project_id"
            placeholder="全部"
            clearable
            style="width: 160px"
          >
            <el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select
            v-model="filters.status"
            placeholder="全部"
            clearable
            style="width: 120px"
          >
            <el-option
              v-for="s in STATUS_OPTIONS"
              :key="s"
              :label="s"
              :value="s"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模板库">
          <el-switch v-model="filters.is_template" @change="loadJobs" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadJobs">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
      <el-button v-if="canAdd" type="primary" @click="openCreate">
        新建作业计划
      </el-button>
    </div>

    <el-card class="gantt-card" shadow="never">
      <template #header>
        <div class="gantt-card-head">
          <span>作业计划甘特视图</span>
          <span class="gantt-card-sub">按 plan_start~plan_end 时间窗展示（红=监控中）</span>
        </div>
      </template>
      <WorkPlanGantt :plans="ganttPlans" @select="openDetail" />
    </el-card>

    <el-table :data="list" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="计划名称" min-width="160">
        <template #default="{ row }">
          <el-tag v-if="row.is_template" size="small" type="warning" effect="plain" style="margin-right: 6px">模板</el-tag>
          {{ row.name }}
        </template>
      </el-table-column>
      <el-table-column label="项目" min-width="140">
        <template #default="{ row }">{{ row.project_name || "-" }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="是否启动" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_start ? 'success' : 'info'" size="small">
            {{ row.is_start ? "是" : "否" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="监控状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.active ? 'danger' : 'info'" size="small" effect="dark">
            {{ row.active ? "监控中" : "未激活" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="plan_time" label="计划时间" width="150" />
      <el-table-column label="绑定" width="150">
        <template #default="{ row }">
          <span class="cnt">人 {{ (row.persons || []).length }}</span>
          <span class="cnt">机 {{ (row.machines || []).length }}</span>
          <span class="cnt">设 {{ (row.devices || []).length }}</span>
          <span class="cnt">栏 {{ (row.fences || []).length }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">查看</el-button>
          <el-button
            v-if="canEdit"
            link
            type="primary"
            @click="openEdit(row)"
          >
            编辑
          </el-button>
          <el-button
            v-if="canEdit && !row.active && row.status !== '已完成'"
            link
            type="success"
            @click="startPlan(row)"
          >
            启动
          </el-button>
          <el-button
            v-if="canEdit && row.active"
            link
            type="warning"
            @click="completePlan(row)"
          >
            完成
          </el-button>
          <el-button
            v-if="canDelete"
            link
            type="danger"
            @click="handleDelete(row)"
          >
            删除
          </el-button>
          <el-button
            v-if="canAdd"
            link
            type="primary"
            @click="clonePlan(row)"
          >
            克隆
          </el-button>
          <el-button
            v-if="canAdd && !row.is_template"
            link
            type="warning"
            @click="saveTemplate(row)"
          >
            存为模板
          </el-button>
        </template>
      </el-table-column>
      <template #empty>暂无作业计划</template>
    </el-table>

    <div class="pager">
      <span>共 {{ total }} 条</span>
    </div>

    <!-- 三步式向导 -->
    <el-dialog
      v-model="wizardVisible"
      :title="wizardMode === 'create' ? '新建作业计划' : '编辑作业计划'"
      width="640px"
    >
      <el-steps :active="activeStep" finish-status="success" align-center>
        <el-step title="基本信息" />
        <el-step title="绑定资源" />
        <el-step title="围栏与规则" />
      </el-steps>

      <div class="step-body">
        <!-- 步骤1 -->
        <template v-if="activeStep === 0">
          <el-form label-width="88px">
            <el-form-item label="所属项目">
              <el-select
                v-model="form.project_id"
                placeholder="选择项目"
                clearable
                style="width: 100%"
              >
                <el-option
                  v-for="p in projects"
                  :key="p.id"
                  :label="p.name"
                  :value="p.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="计划名称" required>
              <el-input v-model="form.name" placeholder="请输入计划名称" />
            </el-form-item>
            <el-form-item label="是否启动">
              <el-switch v-model="form.is_start" />
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width: 100%">
                <el-option
                  v-for="s in STATUS_OPTIONS"
                  :key="s"
                  :label="s"
                  :value="s"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="计划时间窗">
              <div class="time-range">
                <el-date-picker
                  v-model="form.plan_start"
                  type="datetime"
                  placeholder="开始时间"
                  value-format="YYYY-MM-DDTHH:mm:ss"
                  style="width: 100%"
                />
                <span class="range-sep">~</span>
                <el-date-picker
                  v-model="form.plan_end"
                  type="datetime"
                  placeholder="结束时间"
                  value-format="YYYY-MM-DDTHH:mm:ss"
                  style="width: 100%"
                />
              </div>
            </el-form-item>
            <el-form-item label="说明">
              <el-input
                v-model="form.description"
                type="textarea"
                :rows="2"
                placeholder="计划说明（可选）"
              />
            </el-form-item>
          </el-form>
        </template>

        <!-- 步骤2 -->
        <template v-else-if="activeStep === 1">
          <el-form label-width="88px">
            <el-form-item label="绑定人员">
              <el-select
                v-model="form.person_ids"
                multiple
                filterable
                placeholder="选择人员"
                style="width: 100%"
              >
                <el-option
                  v-for="p in persons"
                  :key="p.id"
                  :label="`${p.name}（${p.person_no}）`"
                  :value="p.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="绑定机械">
              <el-select
                v-model="form.machine_ids"
                multiple
                filterable
                placeholder="选择机械"
                style="width: 100%"
              >
                <el-option
                  v-for="m in machines"
                  :key="m.id"
                  :label="`${m.machine_type || m.spec_model || '机械'}（${m.machine_no}）`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="绑定设备">
              <el-select
                v-model="deviceValues"
                multiple
                filterable
                placeholder="选择设备（类型·编号）"
                style="width: 100%"
              >
                <el-option
                  v-for="d in devices"
                  :key="`${d.device_type}::${d.device_no}`"
                  :label="deviceOptionLabel(d)"
                  :value="`${d.device_type}::${d.device_no}`"
                />
              </el-select>
            </el-form-item>
          </el-form>
        </template>

        <!-- 步骤3 -->
        <template v-else>
          <el-form label-width="100px">
            <el-form-item label="绑定围栏">
              <el-select
                v-model="form.fence_ids"
                multiple
                filterable
                placeholder="选择围栏"
                style="width: 100%"
              >
                <el-option
                  v-for="f in fences"
                  :key="f.id"
                  :label="f.name"
                  :value="f.id"
                />
              </el-select>
            </el-form-item>
            <el-divider>规则配置</el-divider>
            <el-form-item label="监控目标">
              <el-input
                v-model="form.rule.monitor_target"
                placeholder="如 人员 / 大机"
              />
            </el-form-item>
            <el-form-item label="触发条件">
              <el-select
                v-model="form.rule.trigger_conditions"
                multiple
                placeholder="选择触发条件（可多选）"
                style="width: 100%"
              >
                <el-option label="围栏侵入" value="fence_intrusion" />
                <el-option label="间距过近" value="distance_too_close" />
                <el-option label="设备自报(列车/大机)" value="device_alarm" />
              </el-select>
            </el-form-item>
            <el-form-item label="时间范围">
              <el-input
                v-model="form.rule.time_range"
                placeholder="如 08:00-18:00"
              />
            </el-form-item>
            <el-form-item label="停留时间">
              <el-input-number
                v-model="form.rule.dwell_time"
                :min="0"
                :max="86400"
              />
              <span class="unit">秒</span>
            </el-form-item>
          </el-form>
        </template>
      </div>

      <template #footer>
        <el-button @click="wizardVisible = false">取消</el-button>
        <el-button v-if="activeStep > 0" @click="activeStep -= 1">上一步</el-button>
        <el-button v-if="activeStep < 2" type="primary" @click="nextStep">
          下一步
        </el-button>
        <el-button
          v-else
          type="primary"
          :loading="saving"
          @click="submitWizard"
        >
          提交
        </el-button>
      </template>
    </el-dialog>

    <!-- 详情 -->
    <el-dialog v-model="detailVisible" title="作业计划详情" width="560px">
      <template v-if="detail">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="计划名称">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="所属项目">
            {{ detail.project_name || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            {{ detail.status }}
          </el-descriptions-item>
          <el-descriptions-item label="是否启动">
            {{ detail.is_start ? "是" : "否" }}
          </el-descriptions-item>
          <el-descriptions-item label="监控状态">
            <el-tag :type="detail.active ? 'danger' : 'info'" size="small" effect="dark">
              {{ detail.active ? "监控中" : "未激活" }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="计划时间窗">
            <template v-if="detail.plan_start || detail.plan_end">
              {{ detail.plan_start || "?" }} ~ {{ detail.plan_end || "?" }}
            </template>
            <template v-else>{{ detail.plan_time || "-" }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="说明">
            {{ detail.description || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="绑定人员">
            {{ (detail.persons || []).map((p) => p.name).join("、") || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="绑定机械">
            {{ (detail.machines || []).map((m) => m.name).join("、") || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="绑定设备">
            {{
              (detail.devices || [])
                .map(
                  (d) =>
                    `${DEVICE_TYPE_LABELS[d.device_type as keyof typeof DEVICE_TYPE_LABELS] || d.device_type}·${d.device_no}`,
                )
                .join("、") || "-"
            }}
          </el-descriptions-item>
          <el-descriptions-item label="绑定围栏">
            {{ (detail.fences || []).map((f) => f.name).join("、") || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="规则">
            <span v-if="detail.rule">
              目标：{{ detail.rule.monitor_target || "-" }}；条件：{{
                (detail.rule.trigger_conditions && detail.rule.trigger_conditions.length)
                  ? detail.rule.trigger_conditions.join("、")
                  : (detail.rule.trigger_condition || "-")
              }}；时间：{{ detail.rule.time_range || "-" }}；停留：{{
                detail.rule.dwell_time ?? "-"
              }}秒
            </span>
            <span v-else>-</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-divider content-position="left">现场照片 / 附件</el-divider>
        <AttachmentManager entityType="work_plan" :entityId="detail?.id ?? null" />
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.filters { flex-wrap: wrap; }
.cnt { margin-right: 8px; font-size: 12px; color: #606266; }
.gantt-card { margin-bottom: 12px; }
.gantt-card-head { display: flex; align-items: baseline; gap: 10px; }
.gantt-card-sub { font-size: 12px; color: #909399; font-weight: normal; }
.pager { margin-top: 12px; color: #606266; font-size: 13px; }
.step-body { padding: 16px 4px 4px; min-height: 240px; }
.unit { margin-left: 8px; color: #909399; font-size: 12px; }
.time-range { display: flex; align-items: center; gap: 8px; width: 100%; }
.range-sep { color: #909399; }
</style>
