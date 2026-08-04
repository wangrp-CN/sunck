<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { fetchProjects } from "@/api/project";
import {
  createAlarmPolicy,
  deleteAlarmPolicy,
  getAlarmPolicyMeta,
  listAlarmPolicies,
  runEscalations,
  updateAlarmPolicy,
  type AlarmPolicy,
  type AlarmPolicyMeta,
  type AlarmPolicyPayload,
} from "@/api/alarm-policy";

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission("alarm_policy:manage"));

const items = ref<AlarmPolicy[]>([]);
const total = ref(0);
const loading = ref(false);
const page = ref(1);
const size = ref(20);

const projects = ref<{ id: number; name: string }[]>([]);
const meta = ref<AlarmPolicyMeta>({
  alarm_types: [],
  levels: ["提示", "警告", "严重"],
  channels: ["in_app", "sms", "voice"],
});

const filterProject = ref<number | null>(null);
const filterType = ref<string>("");
const filterEnabled = ref<boolean | null>(null);

const channelLabels: Record<string, string> = {
  in_app: "站内信",
  sms: "短信",
  voice: "语音",
};
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
  if (!key) return "全部类型";
  return meta.value.alarm_types.find((t) => t.key === key)?.label || key;
}
function channelText(s: string | null | undefined): string {
  if (!s) return "—";
  return s
    .split(",")
    .map((c) => channelLabels[c] || c)
    .join("、");
}

async function load() {
  loading.value = true;
  try {
    const res = await listAlarmPolicies({
      project_id: filterProject.value || undefined,
      alarm_type: filterType.value || undefined,
      enabled: filterEnabled.value === null ? undefined : filterEnabled.value,
      page: page.value,
      size: size.value,
    });
    items.value = res.items;
    total.value = res.total;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载策略失败");
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
  enabled: true,
  suppress_window_seconds: null as number | null,
  silence_start: "" as string,
  silence_end: "" as string,
  escalate_after_minutes: null as number | null,
  escalate_to_level: "严重",
  escalate_channels: ["in_app"] as string[],
  note: "" as string,
});

function resetForm() {
  form.value = {
    name: "",
    project_id: filterProject.value || null,
    alarm_type: "",
    enabled: true,
    suppress_window_seconds: null,
    silence_start: "",
    silence_end: "",
    escalate_after_minutes: null,
    escalate_to_level: "严重",
    escalate_channels: ["in_app"],
    note: "",
  };
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: AlarmPolicy) {
  editingId.value = row.id;
  form.value = {
    name: row.name,
    project_id: row.project_id,
    alarm_type: row.alarm_type || "",
    enabled: row.enabled,
    suppress_window_seconds: row.suppress_window_seconds,
    silence_start: row.silence_start || "",
    silence_end: row.silence_end || "",
    escalate_after_minutes: row.escalate_after_minutes,
    escalate_to_level: row.escalate_to_level || "严重",
    escalate_channels: (row.escalate_channels || "in_app").split(",").filter(Boolean),
    note: row.note || "",
  };
  dialogVisible.value = true;
}

async function submitForm() {
  if (!form.value.name.trim()) {
    ElMessage.warning("请填写策略名称");
    return;
  }
  submitting.value = true;
  const payload: AlarmPolicyPayload = {
    name: form.value.name.trim(),
    project_id: form.value.project_id || null,
    alarm_type: form.value.alarm_type || null,
    enabled: form.value.enabled,
    suppress_window_seconds: form.value.suppress_window_seconds || null,
    // 空串 = 清除静默时段；非空按 HH:MM 提交
    silence_start: form.value.silence_start,
    silence_end: form.value.silence_end,
    escalate_after_minutes: form.value.escalate_after_minutes || null,
    escalate_to_level: form.value.escalate_to_level || "严重",
    escalate_channels: form.value.escalate_channels.join(",") || "in_app",
    note: form.value.note || null,
  };
  try {
    if (editingId.value) {
      await updateAlarmPolicy(editingId.value, payload);
      ElMessage.success("策略已更新");
    } else {
      await createAlarmPolicy(payload);
      ElMessage.success("策略已新增");
    }
    dialogVisible.value = false;
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    submitting.value = false;
  }
}

async function removeRow(row: AlarmPolicy) {
  try {
    await ElMessageBox.confirm(`确认删除策略「${row.name}」？`, "删除确认", { type: "warning" });
  } catch {
    return;
  }
  try {
    await deleteAlarmPolicy(row.id);
    ElMessage.success("已删除");
    load();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

// ---- 手动触发升级扫描 ----
const scanning = ref(false);
async function scanEscalations() {
  scanning.value = true;
  try {
    const r = await runEscalations();
    ElMessage.success(`升级扫描完成：扫描 ${r.scanned} 条，升级 ${r.escalated} 条`);
    if (r.escalated > 0) load();
  } catch (e: any) {
    ElMessage.error(e?.message || "升级扫描失败");
  } finally {
    scanning.value = false;
  }
}

onMounted(async () => {
  await loadProjects();
  try {
    meta.value = await getAlarmPolicyMeta();
  } catch {
    /* 用默认 levels/channels */
  }
  load();
});
</script>

<template>
  <div class="page">
    <div class="bar">
      <span class="title">告警策略</span>
      <div class="bar-actions">
        <el-button v-if="canManage" type="warning" :loading="scanning" @click="scanEscalations">
          立即扫描升级
        </el-button>
        <el-button v-if="canManage" type="primary" @click="openCreate">新增策略</el-button>
      </div>
    </div>

    <el-alert
      class="hint"
      title="策略用于告警收敛（覆盖风暴合并窗口）、抑制（静默时段免打扰）与升级（超时未处理自动升级级别并重通知，含当班人）"
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
      <el-select v-model="filterEnabled as any" clearable placeholder="启用状态" style="width: 140px">
        <el-option label="全部" :value="null" />
        <el-option label="已启用" :value="true" />
        <el-option label="已停用" :value="false" />
      </el-select>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="items" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="归属" min-width="120">
        <template #default="{ row }">{{ row.project_name || "全局" }}</template>
      </el-table-column>
      <el-table-column label="类型" min-width="110">
        <template #default="{ row }">{{ typeLabel(row.alarm_type) }}</template>
      </el-table-column>
      <el-table-column label="启用" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? "启用" : "停用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="收敛窗口" min-width="100" align="center">
        <template #default="{ row }">{{ row.suppress_window_seconds ? row.suppress_window_seconds + "s" : "全局默认" }}</template>
      </el-table-column>
      <el-table-column label="静默时段" min-width="130">
        <template #default="{ row }">
          <span v-if="row.silence_start && row.silence_end">{{ row.silence_start }} ~ {{ row.silence_end }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="升级" min-width="150">
        <template #default="{ row }">
          <span v-if="row.escalate_after_minutes">
            超时 {{ row.escalate_after_minutes }}min →
            <el-tag :type="(levelTag[row.escalate_to_level] as any)" size="small">{{ row.escalate_to_level }}</el-tag>
          </span>
          <span v-else class="muted">不升级</span>
        </template>
      </el-table-column>
      <el-table-column label="通知渠道" min-width="120">
        <template #default="{ row }">{{ channelText(row.escalate_channels) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right" v-if="canManage">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无策略</template>
    </el-table>

    <el-pagination :current-page="page" :page-size="size" :total="total" class="pager" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next, jumper" @size-change="(s: number) => { size = s; }" @current-change="(p: number) => { page = p; load(); }" />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑策略' : '新增策略'"
      width="560px"
    >
      <el-form label-width="110px">
        <el-form-item label="策略名称" required>
          <el-input v-model="form.name" placeholder="如：夜间围栏侵入静默" />
        </el-form-item>
        <el-form-item label="归属项目">
          <el-select v-model="form.project_id as any" clearable filterable placeholder="不选=全局策略" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警类型">
          <el-select v-model="form.alarm_type" clearable style="width: 100%">
            <el-option label="通配（全部类型）" value="" />
            <el-option v-for="t in meta.alarm_types" :key="t.key" :label="t.label" :value="t.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-divider>收敛</el-divider>
        <el-form-item label="合并窗口(秒)">
          <el-input-number v-model="form.suppress_window_seconds as any" :min="0" :controls="false" placeholder="留空=用全局默认" style="width: 100%" />
          <span class="form-hint">覆盖「同源风暴合并」窗口；0 或留空恢复全局默认。</span>
        </el-form-item>
        <el-divider>抑制（静默免打扰）</el-divider>
        <el-form-item label="静默开始">
          <el-input v-model="form.silence_start" placeholder="HH:MM（如 22:00），留空=清除" style="width: 100%" />
        </el-form-item>
        <el-form-item label="静默结束">
          <el-input v-model="form.silence_end" placeholder="HH:MM（如 06:00），支持跨天" style="width: 100%" />
        </el-form-item>
        <el-divider>升级</el-divider>
        <el-form-item label="超时(分钟)">
          <el-input-number v-model="form.escalate_after_minutes as any" :min="0" :controls="false" placeholder="留空=不升级" style="width: 100%" />
          <span class="form-hint">待处理告警超时后自动升级并重通知（含当班人）；0 或留空=关闭。</span>
        </el-form-item>
        <el-form-item label="升级目标级别">
          <el-select v-model="form.escalate_to_level" style="width: 100%">
            <el-option v-for="l in meta.levels" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="通知渠道">
          <el-select v-model="form.escalate_channels" multiple style="width: 100%">
            <el-option v-for="c in meta.channels" :key="c" :label="channelLabels[c] || c" :value="c" />
          </el-select>
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
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.bar-actions { display: flex; gap: 8px; }
.title { font-size: 15px; font-weight: 600; color: #303133; }
.hint { margin-bottom: 12px; }
.filters { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.muted { color: #c0c4cc; font-size: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.form-hint { color: #909399; font-size: 12px; margin-left: 8px; }
</style>
