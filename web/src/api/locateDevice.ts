/**
 * 人机定位设备列表 API（原型《人机定位设备列表》）。
 * 后端 /api/v1/locate-devices 管理 locate_device 表（LocateDevice）。
 */
import { http } from "@/utils/request";
import type {
  LocateDevice,
  LocateDevicePage,
  LocateDeviceCreate,
  LocateDeviceListParams,
  LocateDeviceUpdate,
} from "@/types";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

// 分页列表（项目/名称模糊/类型精确/编号精确/状态精确 过滤，按创建时间倒序）
export function fetchLocateDevices(
  params: LocateDeviceListParams,
): Promise<LocateDevicePage> {
  return http<LocateDevicePage>({
    url: "/v1/locate-devices",
    method: "GET",
    params,
  });
}

// 详情
export function fetchLocateDevice(id: number): Promise<LocateDevice> {
  return http<LocateDevice>({
    url: `/v1/locate-devices/${id}`,
    method: "GET",
  });
}

// 新建
export function createLocateDevice(data: LocateDeviceCreate): Promise<LocateDevice> {
  return http<LocateDevice>({
    url: "/v1/locate-devices",
    method: "POST",
    data,
  });
}

// 更新
export function updateLocateDevice(
  id: number,
  data: LocateDeviceUpdate,
): Promise<LocateDevice> {
  return http<LocateDevice>({
    url: `/v1/locate-devices/${id}`,
    method: "PUT",
    data,
  });
}

// 删除（软删）
export function deleteLocateDevice(id: number): Promise<null> {
  return http<null>({
    url: `/v1/locate-devices/${id}`,
    method: "DELETE",
  });
}

/** 批量删除人机定位设备 */
export function batchDeleteLocateDevices(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/locate-devices/batch-delete", ids);
}
