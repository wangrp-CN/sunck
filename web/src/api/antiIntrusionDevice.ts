/**
 * 大机防侵限设备列表 API（原型《大机防侵限设备列表》）。
 * 后端 /api/v1/anti-intrusion-devices 管理 anti_intrusion_device 表（AntiIntrusionDevice）。
 */
import { http } from "@/utils/request";
import type {
  AntiIntrusionDevice,
  AntiIntrusionDeviceCreate,
  AntiIntrusionDeviceListParams,
  AntiIntrusionDevicePage,
  AntiIntrusionDeviceUpdate,
} from "@/types";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

// 分页列表（项目/名称模糊/编号精确/状态精确 过滤，按创建时间倒序）
export function fetchAntiIntrusionDevices(
  params: AntiIntrusionDeviceListParams,
): Promise<AntiIntrusionDevicePage> {
  return http<AntiIntrusionDevicePage>({
    url: "/v1/anti-intrusion-devices",
    method: "GET",
    params,
  });
}

// 详情
export function fetchAntiIntrusionDevice(id: number): Promise<AntiIntrusionDevice> {
  return http<AntiIntrusionDevice>({
    url: `/v1/anti-intrusion-devices/${id}`,
    method: "GET",
  });
}

// 新建
export function createAntiIntrusionDevice(
  data: AntiIntrusionDeviceCreate,
): Promise<AntiIntrusionDevice> {
  return http<AntiIntrusionDevice>({
    url: "/v1/anti-intrusion-devices",
    method: "POST",
    data,
  });
}

// 更新
export function updateAntiIntrusionDevice(
  id: number,
  data: AntiIntrusionDeviceUpdate,
): Promise<AntiIntrusionDevice> {
  return http<AntiIntrusionDevice>({
    url: `/v1/anti-intrusion-devices/${id}`,
    method: "PUT",
    data,
  });
}

// 删除（软删）
export function deleteAntiIntrusionDevice(id: number): Promise<null> {
  return http<null>({
    url: `/v1/anti-intrusion-devices/${id}`,
    method: "DELETE",
  });
}

/** 批量删除大机防侵限设备 */
export function batchDeleteAntiIntrusionDevices(
  ids: number[],
): Promise<BatchDeleteResult> {
  return batchDelete("/v1/anti-intrusion-devices/batch-delete", ids);
}
