import request, { http } from "@/utils/request";
import type {
  Device,
  DevicePage,
  DeviceCreate,
  DeviceUpdate,
  DeviceHealthResp,
} from "@/types";

// 设备分页列表（device_type 可选，空则跨三类合并）
export function fetchDevices(params: {
  device_type?: string;
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<DevicePage> {
  return http<DevicePage>({
    url: "/v1/devices",
    method: "GET",
    params,
  });
}

// 设备详情
export function fetchDevice(id: number, device_type?: string): Promise<Device> {
  return http<Device>({
    url: `/v1/devices/${id}`,
    method: "GET",
    params: device_type ? { device_type } : undefined,
  });
}

// 新建设备
export function createDevice(data: DeviceCreate): Promise<Device> {
  return http<Device>({
    url: "/v1/devices",
    method: "POST",
    data,
  });
}

// 更新设备
export function updateDevice(
  id: number,
  device_type: string | undefined,
  data: DeviceUpdate,
): Promise<Device> {
  return http<Device>({
    url: `/v1/devices/${id}`,
    method: "PUT",
    params: device_type ? { device_type } : undefined,
    data,
  });
}

// 删除设备（软删）
export function deleteDevice(id: number, device_type: string | undefined): Promise<null> {
  return http<null>({
    url: `/v1/devices/${id}`,
    method: "DELETE",
    params: device_type ? { device_type } : undefined,
  });
}

// 导出设备台账（excel|pdf）——返回二进制 Blob
export async function exportDeviceReport(
  fmt: "excel" | "pdf",
  params: { device_type?: string; keyword?: string },
): Promise<Blob> {
  const resp = await request.get("/v1/devices/export", {
    params: { ...params, fmt },
    responseType: "blob",
  });
  return resp.data as Blob;
}

// 设备健康/运维统计（P3·⑫）：在线判定与实时看板同源
export function fetchDeviceHealth(params?: {
  device_type?: string;
  project_id?: number;
  hours?: number;
}): Promise<DeviceHealthResp> {
  return http<DeviceHealthResp>({
    url: "/v1/devices/health",
    method: "GET",
    params,
  });
}
