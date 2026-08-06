<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
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
type CategoryKey = "all" | "person" | "machine" | "device" | "fence";

const route = useRoute();
const router = useRouter();
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

// ---------- 搜索方式 ----------
const keyword = ref("");
const activeCategory = ref<CategoryKey>("all");
const filteredDevices = computed<MapDevice[]>(() => {
  let list = mapDevices.value;
  if (activeCategory.value !== "all") {
    list = list.filter((d) => {
      if (activeCategory.value === "device") {
        return d.device_type === "locate" || d.device_type === "anti_intrusion" || d.device_type === "train_approach";
      }
      return String(d.device_type) === activeCategory.value;
    });
  }
  const kw = keyword.value.trim().toLowerCase();
  if (kw) {
    list = list.filter(
      (d) => d.name.toLowerCase().includes(kw) || d.device_no.toLowerCase().includes(kw),
    );
  }
  return list;
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

onMounted(async () => {
  await loadProjects();
  await loadDetail();
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
    <div class="info-bar">
      <div v-for="item in infoItems" :key="item.label" class="info-item">
        <span class="info-label">{{ item.label }}</span>
        <el-tooltip :content="String(item.value)" placement="top" :disabled="!item.value || String(item.value).length < 12">
          <span class="info-value">{{ item.value }}</span>
        </el-tooltip>
      </div>
    </div>

    <!-- 搜索方式 -->
    <div class="search-bar">
      <span class="search-label">搜索方式：</span>
      <el-input v-model="keyword" placeholder="按名称 / 编号搜索" clearable style="width: 240px" />
      <el-radio-group v-model="activeCategory" size="small">
        <el-radio-button label="全部" value="all" />
        <el-radio-button label="人员" value="person" />
        <el-radio-button label="大机" value="machine" />
        <el-radio-button label="设备" value="device" />
        <el-radio-button label="围栏" value="fence" />
      </el-radio-group>
    </div>

    <!-- 地图 + 浮动弹窗 -->
    <div class="map-wrap">
      <MapPanel
        ref="mapRef"
        :devices="filteredDevices"
        :fences="mapFences"
        height="100%"
        @device-click="onDeviceClick"
        @fence-click="onFenceClick"
      />

      <!-- 浮动详情弹窗 -->
      <transition name="fade">
        <div v-if="popup.visible" class="detail-popup">
          <div class="popup-header">
            <span v-if="popup.kind === 'device'">设备详情</span>
            <span v-else-if="popup.kind === 'person'">人员详情</span>
            <span v-else-if="popup.kind === 'machine'">大机详情</span>
            <span v-else-if="popup.kind === 'fence'">围栏详情</span>
            <el-button text :icon="'Close'" class="popup-close" @click="closePopup" />
          </div>

          <!-- 人员 -->
          <template v-if="popup.kind === 'person'">
            <div class="popup-row"><span>人员姓名：</span><b>{{ popup.data.name }}</b></div>
            <div class="popup-row"><span>人员编号：</span><b>{{ popup.data.person_no }}</b></div>
            <div class="popup-row"><span>设备名称：</span><b>{{ popup.data.device_no || '—' }}</b></div>
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

          <!-- 设备 -->
          <template v-else-if="popup.kind === 'device'">
            <div class="popup-row"><span>设备名称：</span><b>{{ popup.data.name }}</b></div>
            <div class="popup-row"><span>设备编号：</span><b>{{ popup.data.device_no }}</b></div>
            <div class="popup-row"><span>坐标：</span><b>{{ popup.data.lng }}，{{ popup.data.lat }}</b></div>
            <div v-if="popup.data.direction" class="popup-row"><span>设备方位：</span><b>{{ popup.data.direction }}</b></div>
            <el-button type="primary" plain size="small" @click="viewTrack">查看轨迹</el-button>
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
        </div>
      </transition>
    </div>

    <!-- 告警面板 -->
    <transition name="fade">
      <div v-if="hasAlarms" class="alarm-panel" :class="{ collapsed: alarmPanelCollapsed }">
        <div class="alarm-header" @click="toggleAlarmPanel">
          <span class="alarm-title">待处理告警</span>
          <span class="alarm-count">{{ alarmList.length }}</span>
          <span class="alarm-collapse-icon">{{ alarmPanelCollapsed ? "展开" : "收起" }}</span>
        </div>
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
      </div>
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
.project-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px;
  gap: 12px;
  background: linear-gradient(160deg, #0a1a2f 0%, #0b2238 100%);
  color: #e6f0fa;
}
.dash-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dash-title {
  font-size: 18px;
  font-weight: 600;
  color: #e6f0fa;
}
.spacer {
  flex: 1;
}
.refresh-hint {
  font-size: 12px;
  color: #8aa6c0;
}
.info-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(120, 170, 220, 0.18);
  border-radius: 8px;
}
.info-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
}
.info-label {
  color: #8aa6c0;
  font-size: 13px;
}
.info-value {
  color: #e6f0fa;
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
  color: #8aa6c0;
  font-size: 13px;
}
.map-wrap {
  position: relative;
  flex: 1;
  min-height: 360px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(120, 170, 220, 0.18);
}
.detail-popup {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 280px;
  background: rgba(13, 32, 54, 0.95);
  border: 1px solid rgba(120, 170, 220, 0.35);
  border-radius: 8px;
  padding: 12px 14px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4);
  z-index: 20;
}
.popup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  margin-bottom: 8px;
  color: #7fd0ff;
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
  color: #c4d6e8;
}
.popup-row b {
  color: #e6f0fa;
  font-weight: 600;
}
.popup-row .el-button {
  margin-top: 8px;
}
.alarm-panel {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(120, 170, 220, 0.18);
  border-radius: 8px;
  max-height: 280px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.alarm-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  background: rgba(255, 120, 60, 0.12);
  border-bottom: 1px solid rgba(120, 170, 220, 0.18);
}
.alarm-title {
  font-weight: 600;
  color: #ffb74d;
}
.alarm-count {
  background: #ff6a00;
  color: #fff;
  border-radius: 10px;
  padding: 0 8px;
  font-size: 12px;
}
.alarm-collapse-icon {
  margin-left: auto;
  color: #8aa6c0;
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
  border-bottom: 1px solid rgba(120, 170, 220, 0.12);
}
.alarm-table th {
  color: #8aa6c0;
  font-weight: 600;
  position: sticky;
  top: 0;
  background: #0d2136;
}
.alarm-table td {
  color: #e6f0fa;
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
    background: rgba(255, 106, 0, 0.28);
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
