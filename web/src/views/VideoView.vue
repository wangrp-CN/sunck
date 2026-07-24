<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import {
  fetchVideoChannels,
  createVideoChannel,
  updateVideoChannel,
  deleteVideoChannel,
  fetchVideoEvents,
  handleVideoEvent,
} from "@/api/video";
import { fetchProjects } from "@/api/project";
import type { VideoChannel, VideoEvent, Project } from "@/types";

const auth = useAuthStore();
const canManage = computed(() => auth.user?.permission_codes.includes("video:manage") ?? false);

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
      limit: 200,
    });
  } catch (e: any) {
    ElMessage.error(e?.message || "加载事件失败");
  } finally {
    eventsLoading.value = false;
  }
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
      <el-col :span="13">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span>视频通道</span>
              <el-button v-if="canManage" type="primary" size="small" @click="openCreate">新增通道</el-button>
            </div>
          </template>
          <el-table :data="channels" v-loading="loading" border stripe height="520">
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
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canManage" link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button v-if="canManage" link type="danger" @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>暂无通道</template>
          </el-table>
        </el-card>
      </el-col>

      <!-- AI 事件流 -->
      <el-col :span="11">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span>AI 事件流</span>
              <el-switch v-model="showHandled" @change="loadEvents" active-text="含已处理" />
            </div>
          </template>
          <el-table :data="events" v-loading="eventsLoading" border stripe height="520">
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
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="!row.handled && canManage"
                  link
                  type="primary"
                  @click="doHandle(row)"
                >
                  处理
                </el-button>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <template #empty>暂无事件</template>
          </el-table>
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
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
</style>
