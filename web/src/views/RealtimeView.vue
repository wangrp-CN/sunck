<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  DEVICE_ACTIONS,
  DEVICE_TYPE_LABELS,
  fetchAlarms,
  fetchDevices,
  fetchLocations,
  sendCommand,
  type AlarmItem,
  type DeviceItem,
  type DeviceType,
  type LocationItem,
} from "@/api/realtime";
import { createRealtimeSocket } from "@/utils/ws";
import MapPanel from "@/components/MapPanel.vue";
import WorkPlanPopup from "@/components/WorkPlanPopup.vue";
import type { MapDevice, MapFence } from "@/types";
import { fetchFences } from "@/api/fence";

const devices = ref<DeviceItem[]>([]);
const liveByNo = reactive<Record<string, LocationItem>>({});
const alarms = ref<AlarmItem[]>([]);
const wsConnected = ref(false);
const projectId = ref<number | null>(null);

// 地图与告警联动
const mapRef = ref<InstanceType<typeof MapPanel> | null>(null);
const mapFences = ref<MapFence[]>([]);
const selectedAlarmId = ref<number | null>(null);
// 围栏点击 → 关联作业计划弹层
const planPopup = reactive<{ visible: boolean; fenceId: number | null; fenceName: string }>({
  visible: false,
  fenceId: null,
  fenceName: "",
});
function onFenceClick(f: { id: number; name: string }) {
  planPopup.fenceId = f.id;
  planPopup.fenceName = f.name;
  planPopup.visible = true;
}

function selectAlarm(a: AlarmItem) {
  if (!a.device_no) return;
  selectedAlarmId.value = a.id;
  mapRef.value?.focusDevice(a.device_no);
}

// 指令面板
const cmdDeviceNo = ref("");
const cmdAction = ref("");
const cmdParams = ref("{}");
const cmdLoading = ref(false);

const cmdActions = computed<string[]>(() => {
  const dev = devices.value.find((d) => d.device_no === cmdDeviceNo.value);
  if (!dev) return [];
  return DEVICE_ACTIONS[dev.device_type as DeviceType] || [];
});

// 地图打点：设备配置坐标(无实时时) 与 实时坐标 合并，优先实时 GCJ-02
interface PlotPoint {
  device_no: string;
  name: string;
  device_type: DeviceType;
  lng: number;
  lat: number;
  status: string;
  live: boolean;
}
const plotPoints = computed<PlotPoint[]>(() => {
  const out: PlotPoint[] = [];
  const seen = new Set<string>();
  for (const d of devices.value) {
    seen.add(d.device_no);
    const live = liveByNo[d.device_no];
    if (live && live.gcj02) {
      out.push({
        device_no: d.device_no,
        name: live.device_name || d.name,
        device_type: live.device_type,
        lng: live.gcj02.lng,
        lat: live.gcj02.lat,
        status: live.status,
        live: true,
      });
    } else if (d.longitude != null && d.latitude != null) {
      out.push({
        device_no: d.device_no,
        name: d.name,
        device_type: d.device_type,
        lng: d.longitude,
        lat: d.latitude,
        status: d.status,
        live: false,
      });
    }
  }
  // 仅实时、无配置的设备
  for (const no of Object.keys(liveByNo)) {
    if (seen.has(no)) continue;
    const live = liveByNo[no];
    if (live.gcj02) {
      out.push({
        device_no: no,
        name: live.device_name,
        device_type: live.device_type,
        lng: live.gcj02.lng,
        lat: live.gcj02.lat,
        status: live.status,
        live: true,
      });
    }
  }
  return out;
});

// 地图组件（高德）所需的设备列表与中心点（GCJ-02）
const mapDevices = computed<MapDevice[]>(() =>
  plotPoints.value.map((p) => ({
    device_no: p.device_no,
    name: p.name,
    device_type: p.device_type,
    lng: p.lng,
    lat: p.lat,
    status: p.status,
    live: p.live,
  })),
);

// ----- 实时 socket -----
let closeSocket: (() => void) | null = null;

function onLocation(loc: LocationItem) {
  liveByNo[loc.device_no] = loc;
}
function onAlarm(alarm: AlarmItem) {
  alarms.value.unshift(alarm);
  if (alarms.value.length > 200) alarms.value.pop();
  const level = alarm.alarm_level || "告警";
  ElNotification({
    title: `${level} · ${DEVICE_TYPE_LABELS[alarm.device_type as DeviceType] || alarm.device_type}`,
    message: `${alarm.device_name}（${alarm.device_no}）\n${alarm.alarm_info || ""}`,
    type: alarm.alarm_level === "严重" ? "error" : "warning",
    duration: 6000,
    position: "top-right",
  });
}

// ----- 指令下发 -----
async function submitCommand() {
  if (!cmdDeviceNo.value || !cmdAction.value) {
    ElMessage.warning("请选择设备与指令动作");
    return;
  }
  let params: Record<string, unknown> | null = null;
  if (cmdParams.value && cmdParams.value.trim() !== "{}") {
    try {
      params = JSON.parse(cmdParams.value);
    } catch {
      ElMessage.error("参数 JSON 格式错误");
      return;
    }
  }
  cmdLoading.value = true;
  try {
    const dev = devices.value.find((d) => d.device_no === cmdDeviceNo.value);
    const res = await sendCommand({
      device_type: (dev?.device_type || "locate") as DeviceType,
      device_no: cmdDeviceNo.value,
      action: cmdAction.value,
      params,
    });
    ElMessage.success(`指令已下发 → ${res.topic}`);
  } catch (e: any) {
    ElMessage.error(e?.message || "下发失败");
  } finally {
    cmdLoading.value = false;
  }
}

// ----- 初始化 -----
async function loadAll() {
  try {
    const [devRes, locRes, almRes, fenceRes] = await Promise.all([
      fetchDevices(),
      fetchLocations(),
      fetchAlarms(),
      fetchFences({ page: 1, size: 200 }),
    ]);
    devices.value = devRes.items;
    alarms.value = almRes.items;
    for (const loc of locRes.items) liveByNo[loc.device_no] = loc;
    mapFences.value = (fenceRes.items || []).map((f) => ({
      id: f.id,
      name: f.name,
      geometry_wkt: f.geometry_wkt,
    }));
    // 取第一个项目的 id 用于订阅频道（无项目则订阅 global）
    const firstProj = devices.value.find((d) => d.project_id != null);
    projectId.value = firstProj?.project_id ?? null;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载实时数据失败");
  }
}

onMounted(async () => {
  await loadAll();
  closeSocket = createRealtimeSocket(projectId.value, {
    onLocation,
    onAlarm,
    onStatus: (c) => (wsConnected.value = c),
  });
});

onBeforeUnmount(() => {
  closeSocket?.();
});
</script>

<template>
  <div class="rt">
    <div class="rt-bar">
      <div class="rt-title">实时监控 · 阶段1 实时链路闭环</div>
      <div class="rt-status">
        <span class="dot" :class="wsConnected ? 'on' : 'off'"></span>
        {{ wsConnected ? "WebSocket 已连接" : "WebSocket 未连接" }}
        <el-button size="small" @click="loadAll" style="margin-left: 12px">刷新</el-button>
      </div>
    </div>

    <div class="rt-body">
      <!-- 地图区 -->
      <div class="rt-map">
        <MapPanel
          ref="mapRef"
          :devices="mapDevices"
          :fences="mapFences"
          height="100%"
          @fence-click="onFenceClick"
        />
      </div>

      <!-- 右侧：告警 + 指令 -->
      <div class="rt-side">
        <div class="side-block">
          <div class="side-title">告警列表（实时）</div>
          <div class="alarm-list">
            <el-empty v-if="alarms.length === 0" description="暂无告警" :image-size="60" />
            <div
              v-for="a in alarms"
              :key="a.id"
              class="alarm-item"
              :class="['lv-' + (a.alarm_level || ''), { active: selectedAlarmId === a.id, clickable: !!a.device_no }]"
              @click="selectAlarm(a)"
            >
              <div class="alarm-head">
                <span class="badge" :class="'lv-' + (a.alarm_level || '')">{{ a.alarm_level || '告警' }}</span>
                <span class="at">{{ DEVICE_TYPE_LABELS[a.device_type as DeviceType] || a.device_type }}</span>
                <span class="time">{{ a.alarm_time }}</span>
                <span v-if="a.device_no" class="locate" title="在地图上定位">定位</span>
              </div>
              <div class="alarm-body">{{ a.alarm_info }}</div>
              <div class="alarm-foot">
                {{ a.device_name }}（{{ a.device_no }}）· {{ a.handle_status }}
              </div>
            </div>
          </div>
        </div>

        <div class="side-block">
          <div class="side-title">下发设备指令</div>
          <el-form label-width="72px" size="small">
            <el-form-item label="设备">
              <el-select v-model="cmdDeviceNo" placeholder="选择设备" @change="cmdAction=''">
                <el-option v-for="d in devices" :key="d.device_no" :label="`${d.name}（${d.device_no}）`" :value="d.device_no" />
              </el-select>
            </el-form-item>
            <el-form-item label="动作">
              <el-select v-model="cmdAction" placeholder="选择动作" :disabled="!cmdDeviceNo">
                <el-option v-for="a in cmdActions" :key="a" :label="a" :value="a" />
              </el-select>
            </el-form-item>
            <el-form-item label="参数">
              <el-input v-model="cmdParams" type="textarea" :rows="2" placeholder='JSON，如 {"on": true}' />
            </el-form-item>
            <el-button type="primary" :loading="cmdLoading" @click="submitCommand">下发指令</el-button>
          </el-form>
        </div>
      </div>
    </div>

    <!-- 围栏点击 → 关联作业计划详情 -->
    <WorkPlanPopup
      v-model="planPopup.visible"
      :fence-id="planPopup.fenceId"
      :fence-name="planPopup.fenceName"
    />
  </div>
</template>

<style scoped>
.rt { display: flex; flex-direction: column; height: 100%; }
.rt-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; background: #fff; border-bottom: 1px solid #eee;
}
.rt-title { font-size: 15px; font-weight: 600; }
.rt-status { display: flex; align-items: center; gap: 6px; color: #606266; font-size: 13px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.on { background: #52c41a; }
.dot.off { background: #d9d9d9; }
.rt-body { display: flex; flex: 1; min-height: 0; }
.rt-map { flex: 1; position: relative; background: #f7f9fc; min-height: 360px; }
.rt-side { width: 360px; border-left: 1px solid #eee; display: flex; flex-direction: column; background: #fff; }
.side-block { display: flex; flex-direction: column; min-height: 0; }
.side-block:first-child { flex: 1; border-bottom: 1px solid #eee; }
.side-title { font-weight: 600; padding: 10px 12px 6px; font-size: 14px; }
.alarm-list { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.alarm-item { border: 1px solid #eee; border-left-width: 3px; border-radius: 4px; padding: 8px; margin-bottom: 8px; background: #fafbfc; }
.alarm-item.lv-严重 { border-left-color: #cf1322; }
.alarm-item.lv-警告 { border-left-color: #fa8c16; }
.alarm-item.lv-提示 { border-left-color: #1890ff; }
.alarm-item.clickable { cursor: pointer; transition: box-shadow 0.15s, border-color 0.15s; }
.alarm-item.clickable:hover { box-shadow: 0 1px 6px rgba(22,119,255,.18); }
.alarm-item.active { border-color: #1677ff; box-shadow: 0 0 0 2px rgba(22,119,255,.25); background: #f0f7ff; }
.alarm-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #888; }
.badge { padding: 1px 6px; border-radius: 3px; color: #fff; font-size: 11px; }
.badge.lv-严重 { background: #cf1322; }
.badge.lv-警告 { background: #fa8c16; }
.badge.lv-提示 { background: #1890ff; }
.locate { margin-left: auto; color: #1677ff; font-size: 11px; border: 1px solid #91caff; border-radius: 3px; padding: 0 5px; cursor: pointer; }
.alarm-item.active .locate { background: #1677ff; color: #fff; border-color: #1677ff; }
.alarm-body { margin: 4px 0; font-size: 13px; color: #333; }
.alarm-foot { font-size: 12px; color: #999; }
.side-block:last-child { padding: 0 12px 12px; }
</style>
