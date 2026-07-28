<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Bell, Download, Refresh, Setting } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import {
  createSubscription,
  deleteSubscription,
  downloadSubscription,
  listSubscriptions,
  triggerSubscription,
  updateSubscription,
  type ReportSubscription,
  type SubscriptionCreate,
} from "@/api/subscriptions";
import { fetchProjects } from "@/api/project";
import type { Project } from "@/types";

const auth = useAuthStore();
const isSuper = computed(() => auth.user?.is_superuser ?? false);

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
const CHANNEL_LABELS: Record<string, string> = {
  in_app: "站内信",
  sms: "短信",
  voice: "语音",
};

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
const loading = ref(false);
const loadingList = ref(false);
const list = ref<ReportSubscription[]>([]);
const viewAll = ref(false);
const projectMap = reactive<Record<number, string>>({});

// 编辑对话框
const dialogVisible = ref(false);
const dialogSaving = ref(false);
const editingId = ref<number | null>(null);
const form = reactive<
  SubscriptionCreate & { project_id: number | null; send_weekday: number; send_day: number }
>({
  name: "",
  fmt: "excel",
  days: 30,
  project_id: null,
  frequency: "daily",
  send_hour: 8,
  send_weekday: 0,
  send_day: 1,
  channels: ["in_app"],
  enabled: true,
});

// send_hour 以 "HH:00" 字符串在 el-time-select 上展示，做双向映射
const sendHourModel = computed<string>({
  get: () => String(form.send_hour).padStart(2, "0") + ":00",
  set: (v: string) => {
    form.send_hour = Number(v.slice(0, 2));
  },
});

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------
function freqText(s: ReportSubscription): string {
  const h = String(s.send_hour).padStart(2, "0");
  if (s.frequency === "weekly") return `每周${WEEKDAYS[s.send_weekday]} ${h}:00`;
  if (s.frequency === "monthly") return `每月 ${s.send_day} 日 ${h}:00`;
  return `每日 ${h}:00`;
}
function channelText(channels: string[]): string {
  if (!channels.length) return "—";
  return channels.map((c) => CHANNEL_LABELS[c] || c).join("、");
}
function projectText(s: ReportSubscription): string {
  if (s.project_id == null) return "全量项目";
  return projectMap[s.project_id] || `项目 #${s.project_id}`;
}
function fmtTime(ts: string | null): string {
  if (!ts) return "未运行";
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts;
}
function statusTag(
  s: ReportSubscription,
): { text: string; type: "" | "success" | "danger" | "info" } {
  if (s.last_status === "ok") return { text: "成功", type: "success" };
  if (s.last_status === "failed") return { text: "失败", type: "danger" };
  return { text: "待运行", type: "info" };
}

// ---------------------------------------------------------------------------
// 加载
// ---------------------------------------------------------------------------
async function loadProjects() {
  try {
    const page = await fetchProjects({ page: 1, size: 200 });
    page.items.forEach((p: Project) => {
      projectMap[p.id] = p.name;
    });
  } catch {
    /* 项目名解析失败不影响订阅主流程 */
  }
}

async function loadList() {
  loadingList.value = true;
  try {
    list.value = await listSubscriptions(isSuper.value && viewAll.value);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载订阅列表失败");
  } finally {
    loadingList.value = false;
  }
}

async function refresh() {
  await Promise.all([loadProjects(), loadList()]);
}

// ---------------------------------------------------------------------------
// 新建 / 编辑
// ---------------------------------------------------------------------------
function openCreate() {
  editingId.value = null;
  Object.assign(form, {
    name: "",
    fmt: "excel",
    days: 30,
    project_id: null,
    frequency: "daily",
    send_hour: 8,
    send_weekday: 0,
    send_day: 1,
    channels: ["in_app"],
    enabled: true,
  });
  dialogVisible.value = true;
}

function openEdit(s: ReportSubscription) {
  editingId.value = s.id;
  Object.assign(form, {
    name: s.name,
    fmt: s.fmt,
    days: s.days,
    project_id: s.project_id,
    frequency: s.frequency,
    send_hour: s.send_hour,
    send_weekday: s.send_weekday,
    send_day: s.send_day,
    channels: [...s.channels],
    enabled: s.enabled,
  });
  dialogVisible.value = true;
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning("请填写订阅名称");
    return;
  }
  if ((form.channels?.length ?? 0) === 0) {
    ElMessage.warning("至少选择一个触达渠道");
    return;
  }
  dialogSaving.value = true;
  try {
    const payload: SubscriptionCreate = {
      name: form.name.trim(),
      fmt: form.fmt,
      days: form.days,
      project_id: form.project_id,
      frequency: form.frequency,
      send_hour: form.send_hour,
      send_weekday: form.send_weekday,
      send_day: form.send_day,
      channels: form.channels,
      enabled: form.enabled,
    };
    if (editingId.value == null) {
      await createSubscription(payload);
      ElMessage.success("订阅已创建");
    } else {
      await updateSubscription(editingId.value, payload);
      ElMessage.success("订阅已更新");
    }
    dialogVisible.value = false;
    await loadList();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    dialogSaving.value = false;
  }
}

// ---------------------------------------------------------------------------
// 操作
// ---------------------------------------------------------------------------
async function onTrigger(s: ReportSubscription) {
  try {
    const r = await triggerSubscription(s.id);
    ElMessage.success(`已生成报告（${r.bytes} 字节）并下发通知`);
    await loadList();
  } catch (e: any) {
    ElMessage.error(e?.message || "触发失败");
  }
}

async function onDownload(s: ReportSubscription) {
  try {
    await downloadSubscription(s.id);
  } catch (e: any) {
    ElMessage.error(e?.message || "下载失败");
  }
}

async function onDelete(s: ReportSubscription) {
  try {
    await ElMessageBox.confirm(`确认删除订阅「${s.name}」？`, "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await deleteSubscription(s.id);
    ElMessage.success("已删除");
    await loadList();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

async function onToggleEnabled(s: ReportSubscription, val: boolean) {
  try {
    await updateSubscription(s.id, { enabled: val });
    ElMessage.success(val ? "已启用" : "已暂停");
  } catch (e: any) {
    ElMessage.error(e?.message || "状态更新失败");
    await loadList();
  }
}

onMounted(refresh);
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div class="head-title">
        <el-icon :size="22" class="head-icon"><Bell /></el-icon>
        <div>
          <h2>报告订阅</h2>
          <p class="sub">按自身数据范围订阅「闭环效能运营报告」，到点自动生成并经站内信/短信/语音触达</p>
        </div>
      </div>
      <el-switch
        v-if="isSuper"
        v-model="viewAll"
        active-text="查看全部"
        inline-prompt
        @change="loadList"
      />
    </div>

    <div class="toolbar">
      <el-button type="primary" :icon="Bell" @click="openCreate">新建订阅</el-button>
      <el-button :icon="Refresh" :loading="loadingList" @click="refresh">刷新</el-button>
      <span class="muted">调度由服务端每小时扫描（命中发送的北京时刻即生成）</span>
    </div>

    <el-card shadow="never" class="card">
      <el-table
        :data="list"
        v-loading="loadingList"
        empty-text="暂无订阅，点击「新建订阅」开始"
      >
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="格式" width="80">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.fmt === 'pdf' ? 'warning' : 'success'"
              effect="light"
            >
              {{ row.fmt.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="周期" width="160">
          <template #default="{ row }">{{ freqText(row) }}</template>
        </el-table-column>
        <el-table-column label="窗口" width="90">
          <template #default="{ row }">近 {{ row.days }} 天</template>
        </el-table-column>
        <el-table-column label="聚焦项目" min-width="140">
          <template #default="{ row }">{{ projectText(row) }}</template>
        </el-table-column>
        <el-table-column label="渠道" min-width="140">
          <template #default="{ row }">{{ channelText(row.channels) }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="(v: boolean) => onToggleEnabled(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column label="最近运行" width="160">
          <template #default="{ row }">
            <span class="muted">{{ fmtTime(row.last_run_at) }}</span>
            <el-tag
              v-if="row.last_status"
              size="small"
              :type="statusTag(row).type"
              effect="plain"
            >
              {{ statusTag(row).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Setting" @click="openEdit(row)">编辑</el-button>
            <el-button link type="success" :icon="Bell" @click="onTrigger(row)">立即生成</el-button>
            <el-button link type="primary" :icon="Download" @click="onDownload(row)">下载</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? '新建订阅' : '编辑订阅'"
      width="560px"
      append-to-body
    >
      <el-form :model="form" label-width="110px" v-loading="dialogSaving">
        <el-form-item label="订阅名称" required>
          <el-input v-model="form.name" placeholder="如：每周效能周报" maxlength="128" />
        </el-form-item>
        <el-form-item label="报告格式">
          <el-radio-group v-model="form.fmt">
            <el-radio value="excel">Excel</el-radio>
            <el-radio value="pdf">PDF</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="统计窗口">
          <el-input-number v-model="form.days" :min="7" :max="365" :step="1" />
          <span class="suffix">天</span>
        </el-form-item>
        <el-form-item label="聚焦项目">
          <el-select
            v-model="form.project_id"
            placeholder="全量项目"
            clearable
            filterable
            style="width: 260px"
          >
            <el-option
              v-for="(name, id) in projectMap"
              :key="id"
              :label="name"
              :value="Number(id)"
            />
          </el-select>
          <div class="hint">留空=按您的数据范围统计全部项目</div>
        </el-form-item>
        <el-form-item label="发送频率">
          <el-select v-model="form.frequency" style="width: 160px">
            <el-option label="每日" value="daily" />
            <el-option label="每周" value="weekly" />
            <el-option label="每月" value="monthly" />
          </el-select>
        </el-form-item>
        <el-form-item label="发送时刻(北京)">
          <el-time-select
            v-model="sendHourModel"
            start="00:00"
            end="23:00"
            step="01:00"
            placeholder="选择小时"
            style="width: 160px"
          />
        </el-form-item>
        <el-form-item v-if="form.frequency === 'weekly'" label="发送星期">
          <el-select v-model="form.send_weekday" style="width: 160px">
            <el-option v-for="(w, i) in WEEKDAYS" :key="i" :label="`周${w}`" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.frequency === 'monthly'" label="发送日">
          <el-input-number v-model="form.send_day" :min="1" :max="28" :step="1" />
          <span class="suffix">日</span>
        </el-form-item>
        <el-form-item label="触达渠道">
          <el-checkbox-group v-model="form.channels">
            <el-checkbox value="in_app">站内信</el-checkbox>
            <el-checkbox value="sms">短信</el-checkbox>
            <el-checkbox value="voice">语音</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogSaving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 4px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-icon {
  color: #409eff;
}
.head-title h2 {
  margin: 0;
  font-size: 18px;
}
.sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: #909399;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.muted {
  color: #909399;
  font-size: 12px;
}
.card {
  margin-bottom: 16px;
}
.suffix {
  margin-left: 6px;
  color: #606266;
}
.hint {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
</style>
