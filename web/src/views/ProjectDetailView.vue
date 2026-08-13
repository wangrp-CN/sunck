<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useProjectStore } from "@/stores/project";
import { ElMessage, ElMessageBox } from "element-plus";
import { Monitor } from "@element-plus/icons-vue";
import MapPanel from "@/components/MapPanel.vue";
import { getProjectDetail } from "@/api/dashboard";
import type { ProjectDetailData } from "@/types";
import { alarmTypeLabel, handleAlarm, getTrainApproachRecords } from "@/api/alarm";
import { fetchProjects } from "@/api/project";
import { useAlarmSound } from "@/composables/useAlarmSound";
import type { MapDevice, MapFence, Alarm } from "@/types";

type PopupKind = "" | "device" | "person" | "machine" | "fence";
interface PopupState {
  visible: boolean;
  kind: PopupKind;
  data: any;
}
const route = useRoute();
const router = useRouter();
// 将「大屏选中的项目」写入全局 store，供人员列表等页默认联动
const projectStore = useProjectStore();
const projectId = computed<number | null>(() => {
  const raw = route.params.id;
  return raw !== undefined ? Number(raw) : null;
});

const loading = ref(false);
const detail = ref<ProjectDetailData | null>(null);

const mapRef = ref<InstanceType<typeof MapPanel> | null>(null);

// ---------- 项目切换 ----------
const projectOptions = ref<{ id: number; name: string }[]>([]);
async function loadProjects() {
  try {
    const page = await fetchProjects({ page: 1, size: 1000 });
    projectOptions.value = (page.items || []).map((p: any) => ({ id: p.id, name: p.name }));
  } catch {
    projectOptions.value = [];
  }
}
function onSwitchProject(id: number) {
  if (id && id !== projectId.value) {
    router.push({ name: "project-detail", params: { id } });
  }
}

// ---------- 项目信息栏 ----------
const infoItems = computed(() => {
  const p = detail.value?.project;
  if (!p) return [];
  return [
    { label: "项目简称", value: p.short_name || p.name },
    { label: "开工日期", value: p.start_date || "—" },
    { label: "完工日期", value: p.end_date || "—" },
    { label: "区间", value: p.section || "—" },
    { label: "里程", value: p.mileage || "—" },
  ];
});

// ---------- 地图实体 ----------
const entityByKey = computed<Record<string, { kind: PopupKind; data: any }>>(() => {
  const map: Record<string, { kind: PopupKind; data: any }> = {};
  if (!detail.value) return map;
  for (const d of detail.value.devices) map[d.device_no] = { kind: "device", data: d };
  for (const p of detail.value.persons) map[`P-${p.id}`] = { kind: "person", data: p };
  for (const m of detail.value.machines) map[`M-${m.id}`] = { kind: "machine", data: m };
  for (const f of detail.value.fences) map[`F-${f.id}`] = { kind: "fence", data: f };
  return map;
});

const mapDevices = computed<MapDevice[]>(() => {
  if (!detail.value) return [];
  const out: MapDevice[] = [];
  for (const d of detail.value.devices) {
    if (d.lng == null || d.lat == null) continue;
    out.push({
      device_no: d.device_no,
      name: d.name,
      device_type: d.device_type as MapDevice["device_type"],
      lng: d.lng,
      lat: d.lat,
      status: d.status,
      live: false,
    });
  }
  for (const p of detail.value.persons) {
    if (p.lng == null || p.lat == null) continue;
    out.push({ device_no: `P-${p.id}`, name: p.name, device_type: "person" as any, lng: p.lng, lat: p.lat, status: "在线", live: false });
  }
  for (const m of detail.value.machines) {
    if (m.lng == null || m.lat == null) continue;
    out.push({ device_no: `M-${m.id}`, name: m.machine_no, device_type: "machine" as any, lng: m.lng, lat: m.lat, status: "在线", live: false });
  }
  return out;
});

const mapFences = computed<MapFence[]>(() =>
  (detail.value?.fences || [])
    .filter((f) => f.geometry_wkt)
    .map((f) => ({ id: f.id, name: f.name, geometry_wkt: f.geometry_wkt })),
);

// ---------- 搜索方式（原型：分类下拉 + 取值下拉 → 高亮并展示详情）----------
type SearchKind = "person" | "machine" | "device" | "fence";
const searchKind = ref<SearchKind>("person");
const searchValue = ref<string>("");
const searchLabels: Record<SearchKind, string> = {
  person: "人员姓名",
  machine: "大机编号",
  device: "设备编号",
  fence: "电子围栏名称",
};
const searchOptions = computed<{ label: string; value: string }[]>(() => {
  const d = detail.value;
  if (!d) return [];
  if (searchKind.value === "person") {
    return d.persons.map((p: any) => ({ label: `${p.name}（${p.person_no}）`, value: `P-${p.id}` }));
  }
  if (searchKind.value === "machine") {
    return d.machines.map((m: any) => ({ label: `${m.machine_no}`, value: `M-${m.id}` }));
  }
  if (searchKind.value === "device") {
    return d.devices.map((dv: any) => ({ label: `${dv.name}（${dv.device_no}）`, value: dv.device_no }));
  }
  return d.fences.map((f: any) => ({ label: `${f.name}`, value: `F-${f.id}` }));
});
function onSearchKindChange() {
  searchValue.value = "";
}
function onSearchSelect(value: string) {
  if (!value) return;
  const e = entityByKey.value[value];
  if (!e) return;
  popup.value = { visible: true, kind: e.kind, data: e.data };
  if (e.kind !== "fence") mapRef.value?.focusDevice(value);
}

// 人员绑定设备名称反查（后端 person 仅返回 device_no，设备名称需从 devices 列表反查）
const deviceNameMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {};
  for (const d of detail.value?.devices || []) map[d.device_no] = d.name;
  return map;
});

// ---------- 浮动详情弹窗 ----------
const popup = ref<PopupState>({ visible: false, kind: "", data: null });
function onDeviceClick(payload: { device_no: string; name: string; device_type: string }) {
  const e = entityByKey.value[payload.device_no];
  if (!e) return;
  popup.value = { visible: true, kind: e.kind, data: e.data };
}
function onFenceClick(payload: { id: number; name: string }) {
  const e = entityByKey.value[`F-${payload.id}`];
  if (!e) return;
  popup.value = { visible: true, kind: "fence", data: e.data };
}
function closePopup() {
  popup.value = { visible: false, kind: "", data: null };
}
const currentTrackNo = computed<string | null>(() => {
  const d = popup.value.data;
  if (!d) return null;
  if (popup.value.kind === "device") return d.device_no as string;
  return (d.track_device_no as string) || null;
});
function viewTrack() {
  const no = currentTrackNo.value;
  if (!no) return;
  mapRef.value?.focusDevice(no);
}

// ---------- 列车接近记录（自包含，不影响 AlarmView）----------
const trainDialog = ref(false);
const trainLoading = ref(false);
const trainRecords = ref<Alarm[]>([]);
async function openTrainRecords() {
  const d = popup.value.data;
  if (!d || popup.value.kind !== "device") return;
  trainLoading.value = true;
  try {
    trainRecords.value = await getTrainApproachRecords({
      device_no: d.device_no as string,
      project_id: projectId.value,
    });
    trainDialog.value = true;
  } catch {
    trainRecords.value = [];
  } finally {
    trainLoading.value = false;
  }
}

// ---------- 告警面板 ----------
const alarmList = computed(() => detail.value?.alarms ?? []);
const hasAlarms = computed(() => alarmList.value.length > 0);
const alarmPanelCollapsed = ref(false);
function toggleAlarmPanel() {
  alarmPanelCollapsed.value = !alarmPanelCollapsed.value;
}

const knownAlarmIds = ref<Set<number>>(new Set());
const newAlarmIds = ref<Set<number>>(new Set());
const firstLoad = ref(true);
const sound = useAlarmSound();

function detectNewAlarms(list: { id: number }[]) {
  const ids = new Set(list.map((a) => a.id));
  if (!firstLoad.value) {
    const fresh = list.filter((a) => !knownAlarmIds.value.has(a.id));
    if (fresh.length) {
      newAlarmIds.value = new Set(fresh.map((a) => a.id));
      alarmPanelCollapsed.value = false;
      sound.start();
      window.setTimeout(() => {
        newAlarmIds.value = new Set();
      }, 15000);
    }
  }
  knownAlarmIds.value = ids;
  firstLoad.value = false;
}

function removeAlarm(id: number) {
  if (!detail.value) return;
  detail.value = {
    ...detail.value,
    alarms: detail.value.alarms.filter((a) => a.id !== id),
  };
}

async function handleAlarmRow(alarm: any) {
  let note = "";
  try {
    const res = await ElMessageBox.prompt("请输入处置说明（可选）", "处理告警", {
      confirmButtonText: "确定",
      cancelButtonText: "取消",
      inputType: "textarea",
      inputPlaceholder: "处置说明…",
    });
    note = res.value;
  } catch {
    return;
  }
  await handleAlarm(alarm.id as number, { handle_status: "已处理", content: note || null });
  removeAlarm(alarm.id as number);
  ElMessage.success("告警已处理");
}

async function ignoreAlarmRow(alarm: any) {
  try {
    await ElMessageBox.confirm("您确认忽略当前告警？", "忽略告警", { type: "warning" });
  } catch {
    return;
  }
  await handleAlarm(alarm.id as number, { handle_status: "已忽略" });
  removeAlarm(alarm.id as number);
  ElMessage.success("告警已忽略");
}

// ---------- 无 id 时默认首个项目 ----------
// 菜单入口不带项目 id，进入后自动取项目列表第一个作为默认项目（顶部下拉可切换）。
async function ensureProject() {
  if (projectId.value != null) return;
  try {
    const page = await fetchProjects({ page: 1, size: 1000 });
    const first = (page.items || [])[0];
    if (first) {
      router.replace({ name: "project-detail", params: { id: first.id } });
      return;
    }
  } catch {
    /* ignore */
  }
  ElMessage.warning("暂无可查看的项目");
}

// ---------- 加载 + 自动刷新 ----------
let refreshTimer: ReturnType<typeof setInterval> | null = null;
async function loadDetail() {
  if (projectId.value == null) {
    await ensureProject();
    return;
  }
  loading.value = true;
  try {
    const data = await getProjectDetail(projectId.value);
    detail.value = data;
    detectNewAlarms(data.alarms);
  } catch {
    detail.value = null;
  } finally {
    loading.value = false;
  }
}

function startRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(loadDetail, 15000);
}
function stopRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

watch(
  () => route.params.id,
  () => {
    knownAlarmIds.value = new Set();
    newAlarmIds.value = new Set();
    firstLoad.value = true;
    sound.stop();
    loadDetail();
  },
);

// 当前大屏选中的项目写入全局 store（供人员列表等页默认联动）
watch(projectId, (id) => {
  if (id != null) projectStore.setSelectedProject(id);
});

onMounted(async () => {
  await loadProjects();
  await loadDetail();
  if (projectId.value != null) projectStore.setSelectedProject(projectId.value);
  startRefresh();
});
onUnmounted(() => {
  stopRefresh();
  sound.stop();
});
</script>

<template>
  <div v-loading="loading" class="dashboard project-detail">
    <!-- 顶部工具条 -->
    <div class="dash-toolbar">
      <el-button text :icon="Monitor" @click="router.push({ name: 'dashboard' })">进入智能监控平台</el-button>
      <el-button text :icon="'ArrowLeft'" @click="router.push({ name: 'projects' })">返回</el-button>
      <span class="dash-title">项目详情</span>
      <div class="spacer" />
      <el-select
        :model-value="projectId"
        placeholder="切换项目"
        style="width: 220px"
        @update:model-value="onSwitchProject"
      >
        <el-option v-for="opt in projectOptions" :key="opt.id" :label="opt.name" :value="opt.id" />
      </el-select>
      <span class="refresh-hint">每 15 秒自动刷新</span>
    </div>

    <!-- 项目信息栏 -->
    <el-card class="info-bar" shadow="never">
      <div v-for="item in infoItems" :key="item.label" class="info-item">
        <span class="info-label">{{ item.label }}</span>
        <el-tooltip :content="String(item.value)" placement="top" :disabled="!item.value || String(item.value).length < 12">
          <span class="info-value">{{ item.value }}</span>
        </el-tooltip>
      </div>
    </el-card>

    <!-- 搜索方式（原型：搜索方式下拉 + 取值下拉，选中后高亮并展示详情）-->
    <div class="search-bar">
      <span class="search-label">搜索方式：</span>
      <el-select v-model="searchKind" style="width: 150px" @change="onSearchKindChange">
        <el-option v-for="(label, key) in searchLabels" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select
        v-model="searchValue"
        placeholder="选择具体项"
        filterable
        clearable
        style="width: 260px"
        @change="onSearchSelect"
      >
        <el-option v-for="opt in searchOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
    </div>

    <!-- 地图 + 浮动弹窗 -->
    <div class="map-wrap">
      <MapPanel
        ref="mapRef"
        :devices="mapDevices"
        :fences="mapFences"
        height="100%"
        @device-click="onDeviceClick"
        @fence-click="onFenceClick"
      />

      <!-- 浮动详情弹窗 -->
      <transition name="fade">
        <el-card v-if="popup.visible" class="detail-popup" shadow="never">
          <template #header>
            <div class="popup-header">
              <span v-if="popup.kind === 'device'">设备详情</span>
              <span v-else-if="popup.kind === 'person'">人员详情</span>
              <span v-else-if="popup.kind === 'machine'">大机详情</span>
              <span v-else-if="popup.kind === 'fence'">围栏详情</span>
              <el-button text :icon="'Close'" class="popup-close" @click="closePopup" />
            </div>
          </template>

          <!-- 人员 -->
          <template v-if="popup.kind === 'person'">
            <div class="popup-row"><span>人员姓名：</span><b>{{ popup.data.name }}</b></div>
            <div class="popup-row"><span>人员编号：</span><b>{{ popup.data.person_no }}</b></div>
            <div class="popup-row"><span>设备名称：</span><b>{{ deviceNameMap[popup.data.device_no] || popup.data.device_no || '—' }}</b></div>
            <div class="popup-row"><span>设备编号：</span><b>{{ popup.data.device_no || '—' }}</b></div>
            <div class="popup-row"><span>坐标：</span><b>{{ popup.data.lng }}，{{ popup.data.lat }}</b></div>
            <div class="popup-row"><span>人员类型：</span><b>{{ popup.data.person_type || '—' }}</b></div>
            <el-button type="primary" plain size="small" :disabled="!currentTrackNo" @click="viewTrack">查看轨迹</el-button>
          </template>

          <!-- 大机 -->
          <template v-else-if="popup.kind === 'machine'">
            <div class="popup-row"><span>大机名称：</span><b>{{ popup.data.machine_no }}</b></div>
            <div class="popup-row"><span>大机编号：</span><b>{{ popup.data.machine_no }}</b></div>
            <div class="popup-row"><span>防护人员姓名：</span><b>{{ popup.data.guard_person_name || '—' }}</b></div>
            <div class="popup-row"><span>坐标：</span><b>{{ popup.data.lng }}，{{ popup.data.lat }}</b></div>
            <div class="popup-row"><span>大机类型：</span><b>{{ popup.data.machine_type || '—' }}</b></div>
            <el-button type="primary" plain size="small" :disabled="!currentTrackNo" @click="viewTrack">查看轨迹</el-button>
          </template>

          <!-- 设备（原型 u109：列车接近设备含「设备方位+列车接近记录」；u135 普通设备仅名称/编号/坐标）-->
          <template v-else-if="popup.kind === 'device'">
            <div class="popup-row"><span>设备名称：</span><b>{{ popup.data.name }}</b></div>
            <div class="popup-row"><span>设备编号：</span><b>{{ popup.data.device_no }}</b></div>
            <div class="popup-row"><span>坐标：</span><b>{{ popup.data.lng }}，{{ popup.data.lat }}</b></div>
            <div v-if="popup.data.direction" class="popup-row"><span>设备方位：</span><b>{{ popup.data.direction }}</b></div>
            <el-button
              v-if="popup.data.device_type === 'train_approach'"
              type="warning"
              plain
              size="small"
              :loading="trainLoading"
              @click="openTrainRecords"
            >列车接近记录</el-button>
          </template>

          <!-- 围栏 -->
          <template v-else-if="popup.kind === 'fence'">
            <div class="popup-row"><span>围栏名称：</span><b>{{ popup.data.name }}</b></div>
            <div class="popup-row"><span>围栏编号：</span><b>{{ popup.data.id }}</b></div>
            <div class="popup-row"><span>围栏类型：</span><b>{{ popup.data.fence_type || '—' }}</b></div>
          </template>
        </el-card>
      </transition>
    </div>

    <!-- 告警面板 -->
    <transition name="fade">
      <el-card v-if="hasAlarms" class="alarm-panel" :class="{ collapsed: alarmPanelCollapsed }" shadow="never">
        <template #header>
          <div class="alarm-header" @click="toggleAlarmPanel">
            <span class="alarm-title">告警信息</span>
            <span class="alarm-count">{{ alarmList.length }}</span>
            <span class="alarm-collapse-icon">{{ alarmPanelCollapsed ? "展开" : "收起" }}</span>
          </div>
        </template>
        <div v-show="!alarmPanelCollapsed" class="alarm-body">
          <table class="alarm-table">
            <thead>
              <tr>
                <th>告警类型</th>
                <th>告警信息</th>
                <th>告警时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="alarm in alarmList" :key="alarm.id" :class="{ 'row-new': newAlarmIds.has(alarm.id) }">
                <td>{{ alarmTypeLabel(alarm.alarm_type) }}</td>
                <td class="alarm-info">{{ alarm.alarm_info || '—' }}</td>
                <td>{{ alarm.alarm_time || '—' }}</td>
                <td>
                  <el-button link type="primary" size="small" @click="handleAlarmRow(alarm)">处理</el-button>
                  <el-button link type="info" size="small" @click="ignoreAlarmRow(alarm)">忽略</el-button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </el-card>
    </transition>

    <!-- 列车接近记录对话框 -->
    <el-dialog v-model="trainDialog" title="列车接近记录" width="720px" append-to-body>
      <el-table v-loading="trainLoading" :data="trainRecords" max-height="360">
        <el-table-column prop="alarm_type" label="告警类型">
          <template #default="{ row }">{{ alarmTypeLabel(row.alarm_type) }}</template>
        </el-table-column>
        <el-table-column prop="alarm_info" label="告警信息" show-overflow-tooltip />
        <el-table-column prop="alarm_time" label="告警时间" width="180" />
        <el-table-column prop="handle_status" label="状态" width="100" />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 系统浅色 Element Plus 主题：与监控大屏(DashboardView)及全站卡片一致。
   调色板采用 EP 默认浅色值（#303133/#606266/#909399 文字、#ebeef5 边框、
   #409eff 主色、#f56c6c 危险、#e6a23c 警告），面板复用 el-card shadow=never。 */
.project-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 8px;
  gap: 12px;
}
.dash-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dash-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.spacer {
  flex: 1;
}
.refresh-hint {
  font-size: 12px;
  color: #909399;
}

/* 项目信息卡片：el-card 提供白底 + #ebeef5 描边 + 8px 圆角，与系统一致 */
.info-bar :deep(.el-card__body) {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
}
.info-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
}
.info-label {
  color: #909399;
  font-size: 13px;
}
.info-value {
  color: #303133;
  font-weight: 600;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.search-label {
  color: #606266;
  font-size: 13px;
}
.map-wrap {
  position: relative;
  flex: 1;
  min-height: 360px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #ebeef5;
  background: #fff;
}

/* 浮动详情弹窗：复用 el-card（白底 + EP 描边 + 轻阴影） */
.detail-popup {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 280px;
  z-index: 20;
}
.detail-popup :deep(.el-card__header) {
  padding: 10px 14px;
}
.detail-popup :deep(.el-card__body) {
  padding: 12px 14px;
}
.popup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: #409eff;
}
.popup-close {
  padding: 0;
}
.popup-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  padding: 3px 0;
  color: #606266;
}
.popup-row b {
  color: #303133;
  font-weight: 600;
}
.popup-row .el-button {
  margin-top: 8px;
}

/* 告警面板：el-card 固定高度内滚动，语义化危险色 */
.alarm-panel {
  display: flex;
  flex-direction: column;
  max-height: 280px;
  overflow: hidden;
}
.alarm-panel :deep(.el-card__header) {
  padding: 10px 14px;
  border-bottom: 1px solid #ebeef5;
  flex: 0 0 auto;
}
.alarm-panel :deep(.el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 0;
}
.alarm-header {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.alarm-title {
  font-weight: 600;
  color: #f56c6c;
}
.alarm-count {
  background: #f56c6c;
  color: #fff;
  border-radius: 10px;
  padding: 0 8px;
  font-size: 12px;
}
.alarm-collapse-icon {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.alarm-body {
  overflow: auto;
}
.alarm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.alarm-table th,
.alarm-table td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
}
.alarm-table th {
  color: #606266;
  font-weight: 600;
  position: sticky;
  top: 0;
  background: #f5f7fa;
}
.alarm-table td {
  color: #303133;
}
.alarm-info {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-new {
  animation: row-flash 1.2s ease-in-out 3;
}
@keyframes row-flash {
  0%,
  100% {
    background: transparent;
  }
  50% {
    background: rgba(245, 108, 108, 0.18);
  }
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
