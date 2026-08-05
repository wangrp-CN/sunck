<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { ArrowLeft, ArrowRight, Close, Position } from "@element-plus/icons-vue";
import MapPanel from "@/components/MapPanel.vue";
import { getProjectDetail } from "@/api/dashboard";
import { fetchProjects } from "@/api/project";
import { handleAlarm } from "@/api/alarm";
import type {
  ProjectDetailData,
  ProjectDetailAlarm,
  MapDevice,
  MapFence,
  ProjectPage,
} from "@/types";

const route = useRoute();
const router = useRouter();

// ---- 数据 ----
const loading = ref(false);
const detail = ref<ProjectDetailData | null>(null);
const projectOptions = ref<{ id: number; name: string }[]>([]);
const currentProjectId = ref<number>(Number(route.params.id) || 0);

// ---- 搜索 ----
type SearchType = "person" | "machine" | "device" | "fence";
const searchType = ref<SearchType>("machine");
const searchEntityId = ref<string | number | null>(null);

const searchTypeOptions = [
  { value: "person", label: "人员姓名" },
  { value: "machine", label: "大机编号" },
  { value: "device", label: "设备编号" },
  { value: "fence", label: "电子围栏名称" },
];

const entityOptions = computed(() => {
  const d = detail.value;
  if (!d) return [];
  switch (searchType.value) {
    case "person":
      return d.persons.map((p) => ({ value: p.id, label: `${p.name}（${p.person_no}）` }));
    case "machine":
      return d.machines.map((m) => ({ value: m.id, label: m.machine_no }));
    case "device":
      return d.devices.map((dv) => ({ value: dv.device_no, label: `${dv.name}（${dv.device_no}）` }));
    case "fence":
      return d.fences.map((f) => ({ value: f.id, label: f.name }));
    default:
      return [];
  }
});

// ---- 详情弹窗 ----
type PopupType = "person" | "machine" | "device" | "fence" | null;
const popup = ref<{
  type: PopupType;
  data: Record<string, unknown>;
} | null>(null);

// ---- 告警面板 ----
const alarmPanelCollapsed = ref(false);
const alarmLoading = ref(false);

// ---- 地图 ----
const mapRef = ref<InstanceType<typeof MapPanel> | null>(null);
const mapDevices = ref<MapDevice[]>([]);
const mapFences = ref<MapFence[]>([]);

let timer: number | undefined;

// ============ 数据加载 ============
async function load() {
  if (!currentProjectId.value) return;
  loading.value = true;
  try {
    const data = await getProjectDetail(currentProjectId.value);
    detail.value = data;

    // 地图设备
    mapDevices.value = data.devices.map((d) => ({
      device_no: d.device_no,
      name: d.name,
      device_type: d.device_type as MapDevice["device_type"],
      lng: d.lng,
      lat: d.lat,
      status: d.status,
      live: d.live,
    }));

    // 地图围栏
    mapFences.value = data.fences.map((f) => ({
      id: f.id,
      name: f.name,
      geometry_wkt: f.geometry_wkt,
    }));
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false;
  }
}

async function loadProjectOptions() {
  try {
    const res: ProjectPage = await fetchProjects({ page: 1, size: 200 });
    projectOptions.value = res.items.map((p) => ({ id: p.id, name: p.name }));
  } catch {
    /* ignore */
  }
}

// ============ 搜索 ============
function onSearchTypeChange() {
  searchEntityId.value = null;
  popup.value = null;
}

function onSearch() {
  if (!searchEntityId.value || !detail.value) return;
  const d = detail.value;
  const id = searchEntityId.value;

  switch (searchType.value) {
    case "person": {
      const p = d.persons.find((x) => x.id === id);
      if (p) {
        const dev = d.devices.find((dv) => dv.device_no === p.device_no);
        popup.value = {
          type: "person",
          data: {
            name: p.name,
            person_no: p.person_no,
            person_type: p.person_type || "—",
            device_name: dev?.name || "—",
            device_no: p.device_no || "—",
            lng: dev?.lng,
            lat: dev?.lat,
          },
        };
        if (dev) mapRef.value?.focusDevice(dev.device_no);
      }
      break;
    }
    case "machine": {
      const m = d.machines.find((x) => x.id === id);
      if (m) {
        popup.value = {
          type: "machine",
          data: {
            machine_no: m.machine_no,
            machine_type: m.machine_type || "—",
            description: m.description || "—",
            guard_person_name: m.guard_person_name || "—",
            lng: m.lng,
            lat: m.lat,
            track_device_no: m.track_device_no,
          },
        };
      }
      break;
    }
    case "device": {
      const dv = d.devices.find((x) => x.device_no === id);
      if (dv) {
        popup.value = {
          type: "device",
          data: {
            name: dv.name,
            device_no: dv.device_no,
            device_type: dv.device_type,
            device_type_label: dv.device_type_label,
            lng: dv.lng,
            lat: dv.lat,
          },
        };
        mapRef.value?.focusDevice(dv.device_no);
      }
      break;
    }
    case "fence": {
      const f = d.fences.find((x) => x.id === id);
      if (f) {
        popup.value = {
          type: "fence",
          data: {
            id: f.id,
            name: f.name,
            fence_type: f.fence_type || "—",
          },
        };
      }
      break;
    }
  }
}

// ============ 地图点击 ============
function onDeviceClick(payload: { device_no: string; name: string; device_type: string }) {
  if (!detail.value) return;
  const dv = detail.value.devices.find((d) => d.device_no === payload.device_no);
  if (!dv) return;

  // 检查是否是人员绑定设备
  const person = detail.value.persons.find((p) => p.device_no === payload.device_no);
  if (person) {
    popup.value = {
      type: "person",
      data: {
        name: person.name,
        person_no: person.person_no,
        person_type: person.person_type || "—",
        device_name: dv.name,
        device_no: dv.device_no,
        lng: dv.lng,
        lat: dv.lat,
      },
    };
    return;
  }

  // 检查是否是大机防侵限设备（大机关联）
  if (dv.device_type === "anti_intrusion") {
    // 大机防侵限设备 → 尝试匹配机械
    popup.value = {
      type: "device",
      data: {
        name: dv.name,
        device_no: dv.device_no,
        device_type: dv.device_type,
        device_type_label: dv.device_type_label,
        lng: dv.lng,
        lat: dv.lat,
      },
    };
    return;
  }

  // 默认设备详情
  popup.value = {
    type: "device",
    data: {
      name: dv.name,
      device_no: dv.device_no,
      device_type: dv.device_type,
      device_type_label: dv.device_type_label,
      lng: dv.lng,
      lat: dv.lat,
    },
  };
}

function onFenceClick(payload: { id: number; name: string }) {
  if (!detail.value) return;
  const f = detail.value.fences.find((x) => x.id === payload.id);
  if (!f) return;
  popup.value = {
    type: "fence",
    data: {
      id: f.id,
      name: f.name,
      fence_type: f.fence_type || "—",
    },
  };
}

// ============ 告警处置 ============
async function handleAlarmAction(alarm: ProjectDetailAlarm, action: "处理" | "忽略") {
  const status = action === "处理" ? "已处理" : "已忽略";
  alarmLoading.value = true;
  try {
    await handleAlarm(alarm.id, { handle_status: status });
    ElMessage.success(`告警已${action}`);
    // 更新本地状态
    if (detail.value) {
      const a = detail.value.alarms.find((x) => x.id === alarm.id);
      if (a) a.handle_status = status;
    }
  } catch {
    // 拦截器已提示
  } finally {
    alarmLoading.value = false;
  }
}

// ============ 查看轨迹 ============
function viewTrack(deviceNo: string | undefined) {
  if (!deviceNo || deviceNo === "—") {
    ElMessage.warning("该人员未绑定设备，无法查看轨迹");
    return;
  }
  const projectId = currentProjectId.value;
  const routeData = router.resolve({
    path: "/track",
    query: { device_no: deviceNo, project_id: String(projectId) },
  });
  window.open(routeData.href, "_blank");
}

// ============ 列车接近记录 ============
function viewTrainRecords(deviceNo: string) {
  ElMessage.info(`设备 ${deviceNo} 的列车接近记录功能开发中`);
}

// ============ 项目切换 ============
function onProjectChange() {
  if (currentProjectId.value) {
    router.push({ name: "project-detail", params: { id: currentProjectId.value } });
  }
}

// ============ 进入监控平台 ============
function gotoDashboard() {
  router.push("/dashboard");
}

// ============ 格式化 ============
function fmtDate(s: string | null): string {
  if (!s) return "—";
  return s.slice(0, 10);
}

function fmtDateTime(s: string | null): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 19);
}

function fmtCoord(lng: unknown, lat: unknown): string {
  if (lng == null || lat == null) return "—";
  return `${Number(lng).toFixed(6)}，${Number(lat).toFixed(6)}`;
}

// ============ 告警级别颜色 ============
function alarmLevelColor(level: string | null): string {
  switch (level) {
    case "严重":
      return "#f56c6c";
    case "警告":
      return "#e6a23c";
    case "提示":
      return "#409eff";
    default:
      return "#909399";
  }
}

// ============ 生命周期 ============
watch(
  () => route.params.id,
  (newId) => {
    if (newId) {
      currentProjectId.value = Number(newId);
      popup.value = null;
      searchEntityId.value = null;
      load();
    }
  },
);

onMounted(async () => {
  await Promise.all([load(), loadProjectOptions()]);
  timer = window.setInterval(() => {
    load();
  }, 15000);
});

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <div class="project-detail" v-loading="loading">
    <!-- 顶部工具栏 -->
    <div class="top-bar">
      <div class="top-left">
        <el-button type="primary" :icon="ArrowLeft" @click="gotoDashboard">
          进入智能监控平台
        </el-button>
      </div>
      <div class="top-center">
        <el-select
          v-model="currentProjectId"
          placeholder="选择项目"
          style="width: 240px"
          @change="onProjectChange"
        >
          <el-option
            v-for="p in projectOptions"
            :key="p.id"
            :label="p.name"
            :value="p.id"
          />
        </el-select>
      </div>
    </div>

    <!-- 项目信息栏 -->
    <div class="info-bar" v-if="detail">
      <span class="info-item">
        <span class="info-label">项目简称：</span>
        <span class="info-value">{{ detail.project.short_name || detail.project.name }}</span>
      </span>
      <span class="info-item">
        <span class="info-label">开工日期：</span>
        <span class="info-value">{{ fmtDate(detail.project.start_date) }}</span>
      </span>
      <span class="info-item">
        <span class="info-label">完工日期：</span>
        <span class="info-value">{{ fmtDate(detail.project.end_date) }}</span>
      </span>
      <span class="info-item">
        <span class="info-label">区间：</span>
        <span class="info-value">{{ detail.project.section || "—" }}</span>
      </span>
      <span class="info-item">
        <span class="info-label">里程：</span>
        <span class="info-value">{{ detail.project.mileage || "—" }}</span>
      </span>
    </div>

    <!-- 搜索区域 -->
    <div class="search-bar">
      <span class="search-label">搜索方式：</span>
      <el-select
        v-model="searchType"
        style="width: 160px"
        @change="onSearchTypeChange"
      >
        <el-option
          v-for="opt in searchTypeOptions"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
      <el-select
        v-model="searchEntityId"
        style="width: 220px; margin-left: 10px"
        :placeholder="`请选择${searchTypeOptions.find(o => o.value === searchType)?.label || ''}`"
        filterable
      >
        <el-option
          v-for="opt in entityOptions"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
      <el-button type="primary" style="margin-left: 10px" @click="onSearch">
        搜索
      </el-button>
    </div>

    <!-- 主体区域：地图 + 告警面板 -->
    <div class="main-area">
      <!-- 地图 -->
      <div class="map-container">
        <MapPanel
          ref="mapRef"
          :devices="mapDevices"
          :fences="mapFences"
          :height="'100%'"
          @device-click="onDeviceClick"
          @fence-click="onFenceClick"
        />

        <!-- 浮动详情弹窗 -->
        <transition name="popup-fade">
          <div v-if="popup" class="detail-popup">
            <div class="popup-header">
              <span class="popup-title">
                {{ popup.type === 'person' ? '人员详情' :
                   popup.type === 'machine' ? '大机详情' :
                   popup.type === 'device' ? '设备详情' :
                   popup.type === 'fence' ? '围栏详情' : '详情' }}
              </span>
              <el-icon class="popup-close" @click="popup = null"><Close /></el-icon>
            </div>
            <div class="popup-body">
              <!-- 人员详情 -->
              <template v-if="popup.type === 'person'">
                <div class="popup-row"><span class="pr-label">人员姓名：</span>{{ popup.data.name }}</div>
                <div class="popup-row"><span class="pr-label">人员编号：</span>{{ popup.data.person_no }}</div>
                <div class="popup-row"><span class="pr-label">人员类型：</span>{{ popup.data.person_type }}</div>
                <div class="popup-row"><span class="pr-label">设备名称：</span>{{ popup.data.device_name }}</div>
                <div class="popup-row"><span class="pr-label">设备编号：</span>{{ popup.data.device_no }}</div>
                <div class="popup-row"><span class="pr-label">坐标：</span>{{ fmtCoord(popup.data.lng, popup.data.lat) }}</div>
                <div class="popup-actions">
                  <el-button size="small" type="primary" :icon="Position" @click="viewTrack(popup.data.device_no as string)">
                    查看轨迹
                  </el-button>
                </div>
              </template>

              <!-- 大机详情（图2：大机名称/大机编号/防护人员姓名/坐标/大机类型 + 查看轨迹） -->
              <template v-else-if="popup.type === 'machine'">
                <div class="popup-row"><span class="pr-label">大机名称：</span>{{ popup.data.description || '—' }}</div>
                <div class="popup-row"><span class="pr-label">大机编号：</span>{{ popup.data.machine_no }}</div>
                <div class="popup-row"><span class="pr-label">防护人员姓名：</span>{{ popup.data.guard_person_name }}</div>
                <div class="popup-row"><span class="pr-label">坐标：</span>{{ fmtCoord(popup.data.lng, popup.data.lat) }}</div>
                <div class="popup-row"><span class="pr-label">大机类型：</span>{{ popup.data.machine_type }}</div>
                <div class="popup-actions">
                  <el-button
                    size="small"
                    type="primary"
                    :icon="Position"
                    :disabled="!popup.data.track_device_no"
                    @click="viewTrack(popup.data.track_device_no as string)"
                  >
                    查看轨迹
                  </el-button>
                </div>
              </template>

              <!-- 设备详情 -->
              <template v-else-if="popup.type === 'device'">
                <div class="popup-row"><span class="pr-label">设备名称：</span>{{ popup.data.name }}</div>
                <div class="popup-row"><span class="pr-label">设备编号：</span>{{ popup.data.device_no }}</div>
                <div class="popup-row"><span class="pr-label">设备类型：</span>{{ popup.data.device_type_label }}</div>
                <div class="popup-row"><span class="pr-label">坐标：</span>{{ fmtCoord(popup.data.lng, popup.data.lat) }}</div>
                <div class="popup-row"><span class="pr-label">设备方位：</span>{{ popup.data.device_type === 'train_approach' ? '上行' : '—' }}</div>
                <div class="popup-actions">
                  <el-button
                    v-if="popup.data.device_type === 'train_approach'"
                    size="small"
                    type="primary"
                    @click="viewTrainRecords(popup.data.device_no as string)"
                  >
                    列车接近记录
                  </el-button>
                  <el-button
                    v-else
                    size="small"
                    type="primary"
                    :icon="Position"
                    @click="viewTrack(popup.data.device_no as string)"
                  >
                    查看轨迹
                  </el-button>
                </div>
              </template>

              <!-- 围栏详情 -->
              <template v-else-if="popup.type === 'fence'">
                <div class="popup-row"><span class="pr-label">围栏名称：</span>{{ popup.data.name }}</div>
                <div class="popup-row"><span class="pr-label">围栏编号：</span>{{ popup.data.id }}</div>
                <div class="popup-row"><span class="pr-label">围栏类型：</span>{{ popup.data.fence_type }}</div>
              </template>
            </div>
          </div>
        </transition>
      </div>

      <!-- 告警信息面板（右侧可折叠） -->
      <transition name="panel-slide">
        <div v-show="!alarmPanelCollapsed" class="alarm-panel">
          <div class="alarm-header">
            <span class="alarm-title">告警信息</span>
            <el-button
              :icon="ArrowRight"
              size="small"
              circle
              @click="alarmPanelCollapsed = true"
            />
          </div>
          <div class="alarm-table-wrap" v-loading="alarmLoading">
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
                <tr v-for="a in detail?.alarms || []" :key="a.id" :class="{ handled: a.handle_status !== '待处理' }">
                  <td class="col-type">
                    <span class="alarm-level-dot" :style="{ background: alarmLevelColor(a.alarm_level) }"></span>
                    {{ a.alarm_type || "—" }}
                  </td>
                  <td class="col-info">{{ a.alarm_info || "—" }}</td>
                  <td class="col-time">{{ fmtDateTime(a.alarm_time) }}</td>
                  <td class="col-action">
                    <template v-if="a.handle_status === '待处理'">
                      <el-button size="small" type="primary" link @click="handleAlarmAction(a, '处理')">处理</el-button>
                      <el-button size="small" type="info" link @click="handleAlarmAction(a, '忽略')">忽略</el-button>
                    </template>
                    <span v-else class="handled-tag">{{ a.handle_status }}</span>
                  </td>
                </tr>
                <tr v-if="!detail?.alarms?.length">
                  <td colspan="4" class="empty-row">暂无告警信息</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </transition>

      <!-- 展开按钮（折叠时显示） -->
      <transition name="panel-slide">
        <div v-show="alarmPanelCollapsed" class="alarm-panel-collapsed" @click="alarmPanelCollapsed = false">
          <el-icon :size="20"><ArrowLeft /></el-icon>
          <span class="collapsed-text">告警信息</span>
          <span class="collapsed-count" v-if="detail?.alarms?.length">{{ detail.alarms.length }}</span>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.project-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: calc(100vh - 60px);
  background: #f0f2f5;
  padding: 8px;
}

/* 顶部工具栏 */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fff;
  border-radius: 6px;
  margin-bottom: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

/* 项目信息栏 */
.info-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 24px;
  padding: 10px 16px;
  background: #fff;
  border-radius: 6px;
  margin-bottom: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.info-item {
  font-size: 14px;
  white-space: nowrap;
}
.info-label {
  color: #909399;
}
.info-value {
  color: #303133;
  font-weight: 500;
}

/* 搜索区域 */
.search-bar {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  background: #fff;
  border-radius: 6px;
  margin-bottom: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.search-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}

/* 主体区域 */
.main-area {
  flex: 1;
  display: flex;
  gap: 8px;
  min-height: 0;
}

.map-container {
  flex: 1;
  position: relative;
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

/* 浮动详情弹窗 */
.detail-popup {
  position: absolute;
  top: 50px;
  right: 16px;
  width: 220px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  z-index: 10;
  overflow: hidden;
}
.popup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
}
.popup-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.popup-close {
  cursor: pointer;
  color: #909399;
  transition: color 0.2s;
}
.popup-close:hover {
  color: #f56c6c;
}
.popup-body {
  padding: 10px 12px;
}
.popup-row {
  font-size: 13px;
  line-height: 1.8;
  color: #606266;
}
.pr-label {
  color: #909399;
}
.popup-actions {
  margin-top: 8px;
  text-align: center;
}

/* 告警面板 */
.alarm-panel {
  width: 440px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 6px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}
.alarm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
}
.alarm-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.alarm-table-wrap {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 告警表格 */
.alarm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.alarm-table thead {
  position: sticky;
  top: 0;
  z-index: 1;
}
.alarm-table th {
  padding: 8px 6px;
  background: #fafafa;
  color: #606266;
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid #ebeef5;
  white-space: nowrap;
}
.alarm-table td {
  padding: 8px 6px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: top;
}
.alarm-table tbody tr:hover {
  background: #f5f7fa;
}
.alarm-table tr.handled {
  opacity: 0.6;
}
.col-type {
  white-space: nowrap;
}
.col-info {
  max-width: 140px;
  word-break: break-all;
}
.col-time {
  white-space: nowrap;
  color: #909399;
  font-size: 12px;
}
.col-action {
  white-space: nowrap;
}
.alarm-level-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.handled-tag {
  font-size: 12px;
  color: #909399;
}
.empty-row {
  text-align: center;
  color: #c0c4cc;
  padding: 20px;
}

/* 折叠态 */
.alarm-panel-collapsed {
  width: 36px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #fff;
  border-radius: 6px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: background 0.2s;
}
.alarm-panel-collapsed:hover {
  background: #f5f7fa;
}
.collapsed-text {
  writing-mode: vertical-rl;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  letter-spacing: 4px;
}
.collapsed-count {
  font-size: 12px;
  color: #f56c6c;
  font-weight: 700;
}

/* 动画 */
.popup-fade-enter-active,
.popup-fade-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.popup-fade-enter-from,
.popup-fade-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: opacity 0.2s, width 0.2s;
}
.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  width: 0;
}

/* 响应式 */
@media (max-width: 1200px) {
  .alarm-panel {
    width: 360px;
  }
  .col-info {
    max-width: 100px;
  }
}
@media (max-width: 900px) {
  .main-area {
    flex-direction: column;
  }
  .alarm-panel {
    width: 100%;
    max-height: 300px;
  }
  .alarm-panel-collapsed {
    width: 100%;
    height: 36px;
    flex-direction: row;
  }
  .collapsed-text {
    writing-mode: horizontal-tb;
    letter-spacing: 0;
  }
  .detail-popup {
    width: 180px;
  }
}
</style>
