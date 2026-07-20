// 实时链路 API 封装（阶段1）：位置 / 设备 / 告警 / 下发指令 / 轨迹回放
import { http } from "@/utils/request";
import type { TrajectoryPoint } from "@/types";

export type DeviceType = "locate" | "anti_intrusion" | "train_approach";

export interface GcjPoint {
  lng: number;
  lat: number;
}

export interface LocationItem {
  device_type: DeviceType;
  device_no: string;
  device_name: string;
  project_id: number | null;
  longitude: number | null;
  latitude: number | null;
  gcj02: GcjPoint | null;
  accuracy: number | null;
  speed: number | null;
  status: string;
  report_time: string | null;
}

export interface DeviceItem {
  device_type: DeviceType;
  device_type_label: string;
  device_id: number;
  device_no: string;
  name: string;
  project_id: number | null;
  longitude: number | null;
  latitude: number | null;
  status: string;
}

export interface AlarmItem {
  id: number;
  project_id: number | null;
  alarm_type: string;
  device_type: string;
  device_name: string;
  device_no: string;
  alarm_info: string | null;
  alarm_status: string;
  alarm_level: string | null;
  handle_status: string;
  handle_content: string | null;
  fence_name: string | null;
  work_plan_id: number | null;
  media_urls: string[] | null;
  alarm_time: string | null;
}

export interface ListResult<T> {
  total: number;
  items: T[];
}

export interface CommandRequest {
  device_type: DeviceType;
  device_no: string;
  action: string;
  params?: Record<string, unknown> | null;
}

export interface CommandResult {
  topic: string;
  device_type: DeviceType;
  device_no: string;
  action: string;
  payload: Record<string, unknown>;
}

// 最新设备位置（地图实时打点）
export function fetchLocations(projectId?: number): Promise<ListResult<LocationItem>> {
  return http<ListResult<LocationItem>>({
    url: "/v1/realtime/locations",
    method: "GET",
    params: projectId ? { project_id: projectId } : undefined,
  });
}

// 设备列表（地图初始渲染）
export function fetchDevices(projectId?: number): Promise<ListResult<DeviceItem>> {
  return http<ListResult<DeviceItem>>({
    url: "/v1/realtime/devices",
    method: "GET",
    params: projectId ? { project_id: projectId } : undefined,
  });
}

// 告警列表（page/size 真分页，total 为真实总数）
export function fetchAlarms(params?: {
  project_id?: number;
  alarm_type?: string;
  handle_status?: string;
  alarm_status?: string;
  page?: number;
  size?: number;
}): Promise<ListResult<AlarmItem>> {
  return http<ListResult<AlarmItem>>({
    url: "/v1/alarms",
    method: "GET",
    params,
  });
}

// 下发设备指令（接口 2/4/6）
export function sendCommand(req: CommandRequest): Promise<CommandResult> {
  return http<CommandResult>({
    url: "/v1/realtime/command",
    method: "POST",
    data: req,
  });
}

// 各设备类型支持的指令动作（与后端 protocol._DOWNLINK_ACTIONS 对齐）
export const DEVICE_ACTIONS: Record<DeviceType, string[]> = {
  locate: ["upload_interval", "alarm", "sound", "light", "restart"],
  anti_intrusion: ["camera", "capture", "radar_sensitivity", "arm", "barrier", "alarm", "restart"],
  train_approach: ["radar_sensitivity", "alarm", "sound", "restart"],
};

export const DEVICE_TYPE_LABELS: Record<DeviceType, string> = {
  locate: "人机定位",
  anti_intrusion: "大机防侵限",
  train_approach: "列车接近",
};

// 设备轨迹回放（按 device_no + 时间区间，返回有序位置序列）
export function fetchTrajectory(params: {
  device_no: string;
  start: string;
  end: string;
  project_id?: number;
}): Promise<ListResult<TrajectoryPoint>> {
  return http<ListResult<TrajectoryPoint>>({
    url: "/v1/realtime/trajectory",
    method: "GET",
    params,
  });
}

// ===================== 设备在线看板 =====================
export interface OnlineStatusItem {
  device_type: DeviceType;
  device_no: string;
  device_name: string | null;
  project_id: number | null;
  longitude: number | null;
  latitude: number | null;
  gcj02: GcjPoint | null;
  status: string;
  report_time: string | null;
  online: boolean;
  age_seconds: number | null;
}

export interface OnlineStatusByType {
  total: number;
  online: number;
  offline: number;
}

export interface OnlineStatusResult {
  threshold_seconds: number;
  total: number;
  online: number;
  offline: number;
  by_type: Record<string, OnlineStatusByType>;
  items: OnlineStatusItem[];
}

// 设备实时在线状态（基于最近上报时间阈值判定）
export function fetchOnlineStatus(params?: {
  project_id?: number;
  device_type?: string;
}): Promise<OnlineStatusResult> {
  return http<OnlineStatusResult>({
    url: "/v1/realtime/online-status",
    method: "GET",
    params,
  });
}
