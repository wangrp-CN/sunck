<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import ResponsiveTable from "@/components/ResponsiveTable.vue";
import VideoPlayer from "@/components/VideoPlayer.vue";
import {
  fetchVideoChannels,
  createVideoChannel,
  updateVideoChannel,
  deleteVideoChannel,
  fetchVideoEvents,
  handleVideoEvent,
  escalateVideoEvent,
  fetchVideoAiCapabilities,
  analyzeVideo,
} from "@/api/video";
import { fetchProjects } from "@/api/project";
import type { VideoChannel, VideoEvent, Project, VideoAiAnalyzeResult } from "@/types";

const auth = useAuthStore();
const router = useRouter();
// 后端视频写操作统一要求 video:update（含处理/升级）；超管免校验
const canManage = computed(() => auth.hasPermission("video:update"));

const EVENT_TYPE_LABELS: Record<string, string> = {
  intrusion: "区域入侵",
  no_helmet: "未戴安全帽",
  smoke_fire: "烟火",
  other: "其他",
};
function eventLabel(t: string): string {
  return EVENT_TYPE_LABELS[t] || t;
}

const projects = ref<Project[]>([]);
const channels = ref<VideoChannel[]>([]);
const loading = ref(false);

const events = ref<VideoEvent[]>([]);
const eventsLoading = ref(false);
const showHandled = ref(false);
const eventTypeFilter = ref<string | null>(null);

const stats = computed(() => {
  const list = events.value;
  return {
    total: list.length,
    pending: list.filter((e) => !e.handled).length,
    escalated: list.filter((e) => e.alarm_id != null).length,
    handled: list.filter((e) => e.handled).length,
  };
});

async function loadProjects() {
  try {
    const res = await fetchProjects({ page: 1, size: 200 });
    projects.value = res.items;
  } catch {
    /* ignore */
  }
}
async function loadChannels() {
  loading.value = true;
  try {
    channels.value = await fetchVideoChannels();
  } catch (e: any) {
    ElMessage.error(e?.message || "加载通道失败");
  } finally {
    loading.value = false;
  }
}
async function loadEvents() {
  eventsLoading.value = true;
  try {
    events.value = await fetchVideoEvents({
      handled: showHandled.value ? undefined : false,
      event_type: eventTypeFilter.value || undefined,
      limit: 200,
    });
  } catch (e: any) {
    ElMessage.error(e?.message || "加载事件失败");
  } finally {
    eventsLoading.value = false;
  }
}

// 升级为平台告警（闭环联动⑧）：回填 alarm_id，事件列表将展示「查看告警」入口
async function doEscalate(row: VideoEvent) {
  try {
    await escalateVideoEvent(row.id);
    ElMessage.success("已升级为平台告警");
    loadEvents();
  } catch (e: any) {
    ElMessage.error(e?.message || "升级失败");
  }
}

// 跳转告警管理，查看由本事件升级生成的告警
function viewAlarm(_row?: VideoEvent) {
  router.push({ name: "alarms" });
}

// 截图加载失败（外部地址不可达）时隐藏破图
function onSnapError(e: Event) {
  const el = e.target as HTMLImageElement | null;
  if (el) el.style.display = "none";
}
function projectName(id?: number | null) {
  if (id == null) return "—";
  return projects.value.find((p) => p.id === id)?.name ?? `ID:${id}`;
}

// ---- 通道 创建/编辑 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<number | null>(null);
const saving = ref(false);
const form = reactive({
  project_id: null as number | null,
  name: "",
  channel_no: "",
  stream_url: "" as string | null,
  vendor: "" as string | null,
  location_desc: "" as string | null,
  lng: null as number | null,
  lat: null as number | null,
  status: "在线",
  ai_enabled: true,
});

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, {
    project_id: null,
    name: "",
    channel_no: "",
    stream_url: null,
    vendor: null,
    location_desc: null,
    lng: null,
    lat: null,
    status: "在线",
    ai_enabled: true,
  });
  dialogVisible.value = true;
}
async function openEdit(row: VideoChannel) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    project_id: row.project_id ?? null,
    name: row.name,
    channel_no: row.channel_no,
    stream_url: row.stream_url ?? null,
    vendor: row.vendor ?? null,
    location_desc: row.location_desc ?? null,
    lng: row.lng ?? null,
    lat: row.lat ?? null,
    status: row.status,
    ai_enabled: row.ai_enabled,
  });
  dialogVisible.value = true;
}
async function submit() {
  if (!form.name || !form.channel_no) {
    ElMessage.warning("请填写名称与通道编号");
    return;
  }
  saving.value = true;
  try {
    const req = {
      project_id: form.project_id,
      name: form.name,
      channel_no: form.channel_no,
      stream_url: form.stream_url || null,
      vendor: form.vendor || null,
      location_desc: form.location_desc || null,
      lng: form.lng,
      lat: form.lat,
      status: form.status,
      ai_enabled: form.ai_enabled,
    };
    if (dialogMode.value === "create") await createVideoChannel(req);
    else await updateVideoChannel(editingId.value!, req);
    ElMessage.success(dialogMode.value === "create" ? "通道已创建" : "通道已更新");
    dialogVisible.value = false;
    loadChannels();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}
async function handleDelete(row: VideoChannel) {
  try {
    await ElMessageBox.confirm(`确认删除通道「${row.name}」？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await deleteVideoChannel(row.id);
    ElMessage.success("已删除");
    loadChannels();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

// 实时预览（深化⑧）：用 VideoPlayer 拉流播放 stream_url
const previewVisible = ref(false);
const previewUrl = ref<string | null>(null);
const previewName = ref("");
function openPreview(row: VideoChannel) {
  previewUrl.value = row.stream_url ?? null;
  previewName.value = row.name;
  previewVisible.value = true;
}

// 视频 AI 分析（深化⑧）：能力清单 + 发起分析并显示 findings
const aiVisible = ref(false);
const aiChannelNo = ref<string | null>(null);
const aiLoading = ref(false);
const aiResult = ref<VideoAiAnalyzeResult | null>(null);
const capabilities = ref<string[]>([]);

async function loadCapabilities() {
  try {
    const r = await fetchVideoAiCapabilities();
    capabilities.value = r.capabilities || [];
  } catch {
    /* ignore */
  }
}
function openAi(row: VideoChannel) {
  aiChannelNo.value = row.channel_no;
  aiResult.value = null;
  aiVisible.value = true;
  loadCapabilities();
}
async function runAnalyze() {
  if (!aiChannelNo.value) return;
  aiLoading.value = true;
  aiResult.value = null;
  try {
    const res = await analyzeVideo({ channel_no: aiChannelNo.value });
    aiResult.value = res;
    if (res.status === "done") {
      ElMessage.success(`识别完成，共 ${res.findings?.length ?? 0} 项异常`);
    } else if (res.status === "pending_capability") {
      ElMessage.info("视频 AI 识别能力尚未启用");
    } else {
      ElMessage.warning("推理服务未接入或调用失败，已返回占位结果");
    }
  } catch (e: any) {
    ElMessage.error(e?.message || "分析失败");
  } finally {
    aiLoading.value = false;
  }
}
async function doHandle(row: VideoEvent) {
  try {
    await handleVideoEvent(row.id);
    ElMessage.success("已处理");
    loadEvents();
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      /* ignore */
    }
  }
  await loadProjects();
  await loadChannels();
  await loadEvents();
});
</script>

<template>
  <div class="page">
    <el-row :gutter="16">
      <!-- 通道管理 -->
      <el-col :span="13" :xs="24">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span>视频通道</span>
              <el-button v-if="canManage" type="primary" size="small" @click="openCreate">新增通道</el-button>
            </div>
          </template>
          <ResponsiveTable :data="channels" v-loading="loading" border stripe height="520">
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column prop="channel_no" label="编号" width="110" />
            <el-table-column label="项目" min-width="110">
              <template #default="{ row }">{{ projectName(row.project_id) }}</template>
            </el-table-column>
            <el-table-column label="AI" width="70">
              <template #default="{ row }">
                <el-tag :type="row.ai_enabled ? 'success' : 'info'" size="small">
                  {{ row.ai_enabled ? "开" : "关" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === '在线' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openPreview(row)">预览</el-button>
                <el-button v-if="canManage" link type="success" @click="openAi(row)">AI分析</el-button>
                <el-button v-if="canManage" link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button v-if="canManage" link type="danger" @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>暂无通道</template>
          </ResponsiveTable>
        </el-card>
      </el-col>

      <!-- AI 事件流 -->
      <el-col :span="11" :xs="24">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span>AI 事件流</span>
              <div class="head-tools">
                <el-select
                  v-model="eventTypeFilter"
                  placeholder="全部类型"
                  clearable
                  size="small"
                  style="width: 130px"
                  @change="loadEvents"
                >
                  <el-option
                    v-for="(label, key) in EVENT_TYPE_LABELS"
                    :key="key"
                    :label="label"
                    :value="key"
                  />
                </el-select>
                <el-switch v-model="showHandled" @change="loadEvents" active-text="含已处理" />
              </div>
            </div>
          </template>
          <div class="evt-stats">
            <span>事件 <b>{{ stats.total }}</b></span>
            <span>待处理 <b class="warn">{{ stats.pending }}</b></span>
            <span>已升级告警 <b class="ok">{{ stats.escalated }}</b></span>
            <span>已处理 <b>{{ stats.handled }}</b></span>
          </div>
          <ResponsiveTable :data="events" v-loading="eventsLoading" border stripe height="520">
            <el-table-column label="通道" min-width="120">
              <template #default="{ row }">{{ row.channel_name || row.channel_no || "—" }}</template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag :type="row.event_type === 'other' ? 'info' : 'danger'" size="small">
                  {{ eventLabel(row.event_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="置信" width="70">
              <template #default="{ row }">{{ row.confidence != null ? (row.confidence * 100).toFixed(0) + "%" : "—" }}</template>
            </el-table-column>
            <el-table-column label="截图" width="84">
              <template #default="{ row }">
                <img v-if="row.snapshot_url" :src="row.snapshot_url" class="snap" alt="截图" @error="onSnapError" />
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" min-width="130">
              <template #default="{ row }">{{ row.event_time || "—" }}</template>
            </el-table-column>
            <el-table-column label="状态" width="70">
              <template #default="{ row }">
                <el-tag :type="row.handled ? 'success' : 'warning'" size="small">
                  {{ row.handled ? "已处理" : "待处理" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="!row.alarm_id && canManage"
                  link
                  type="primary"
                  @click="doEscalate(row)"
                >
                  升级告警
                </el-button>
                <el-button
                  v-if="row.alarm_id"
                  link
                  type="success"
                  @click="viewAlarm(row)"
                >
                  查看告警
                </el-button>
                <el-button
                  v-if="!row.handled && canManage"
                  link
                  type="primary"
                  @click="doHandle(row)"
                >
                  处理
                </el-button>
                <span v-if="row.handled && !row.alarm_id" class="muted">—</span>
              </template>
            </el-table-column>
            <template #empty>暂无事件</template>
          </ResponsiveTable>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新增视频通道' : '编辑视频通道'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="所属项目">
          <el-select v-model="form.project_id" placeholder="选择项目" clearable style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="通道名称" required>
          <el-input v-model="form.name" placeholder="如 1#隧道口球机" />
        </el-form-item>
        <el-form-item label="通道编号" required>
          <el-input v-model="form.channel_no" placeholder="唯一，如 CH-001" />
        </el-form-item>
        <el-form-item label="拉流地址">
          <el-input v-model="form.stream_url" placeholder="rtsp/rtmp/hls（可选）" />
        </el-form-item>
        <el-form-item label="厂商">
          <el-input v-model="form.vendor" placeholder="可选" />
        </el-form-item>
        <el-form-item label="点位描述">
          <el-input v-model="form.location_desc" placeholder="可选" />
        </el-form-item>
        <el-form-item label="经度"><el-input v-model.number="form.lng" placeholder="可选" style="width: 100%" /></el-form-item>
        <el-form-item label="纬度"><el-input v-model.number="form.lat" placeholder="可选" style="width: 100%" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="在线" value="在线" />
            <el-option label="离线" value="离线" />
          </el-select>
        </el-form-item>
        <el-form-item label="AI 使能">
          <el-switch v-model="form.ai_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交</el-button>
      </template>
    </el-dialog>

    <!-- 实时预览（深化⑧）：拉流播放 -->
    <el-dialog v-model="previewVisible" :title="`实时预览 · ${previewName}`" width="720px">
      <VideoPlayer :url="previewUrl" />
    </el-dialog>

    <!-- 视频 AI 分析（深化⑧）：能力清单 + 发起分析 + 结果 -->
    <el-dialog v-model="aiVisible" title="视频 AI 分析" width="560px">
      <div class="cap-row">
        <span class="cap-label">可识别能力：</span>
        <el-tag v-for="c in capabilities" :key="c" size="small" effect="plain" class="cap-tag">{{ c }}</el-tag>
      </div>
      <el-button type="primary" :loading="aiLoading" @click="runAnalyze">发起分析</el-button>
      <div v-if="aiResult" class="ai-result">
        <el-alert
          :type="aiResult.status === 'done' ? 'success' : aiResult.status === 'pending_capability' ? 'info' : 'warning'"
          :closable="false"
          :title="aiResult.message"
        />
        <ResponsiveTable
          v-if="aiResult.status === 'done' && aiResult.findings && aiResult.findings.length"
          :data="aiResult.findings"
          size="small"
          border
          stripe
          style="margin-top: 10px"
        >
          <el-table-column prop="label" label="类型" min-width="120" />
          <el-table-column label="置信度" width="120">
            <template #default="{ row }">
              {{ row.confidence != null ? (row.confidence * 100).toFixed(0) + "%" : "—" }}
            </template>
          </el-table-column>
        </ResponsiveTable>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
.head-tools { display: flex; align-items: center; gap: 10px; }
.evt-stats {
  display: flex;
  gap: 18px;
  margin-bottom: 10px;
  font-size: 13px;
  color: #606266;
}
.evt-stats b { color: #303133; font-size: 15px; margin-left: 2px; }
.evt-stats b.warn { color: #e6a23c; }
.evt-stats b.ok { color: #67c23a; }
.snap {
  width: 64px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #ebeef5;
  background: #f5f7fa;
}
.muted { color: #c0c4cc; }
.cap-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 12px; }
.cap-label { font-size: 13px; color: #606266; }
.cap-tag { margin-right: 4px; }
.ai-result { margin-top: 12px; }

/* 移动端：缩小留白、统计与筛选工具自动换行 */
@media (max-width: 768px) {
  .page { padding: 8px; }
  .evt-stats { flex-wrap: wrap; gap: 10px; }
  .head-tools { flex-wrap: wrap; }
}
</style>
