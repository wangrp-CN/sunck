/**
 * 列车接近报警设备列表 API（原型《列车接近报警设备列表》）。
 * 后端 /api/v1/train-approach-devices 管理 train_approach_device 表（TrainApproachDevice）。
 */
import { http } from "@/utils/request";
import type {
  TrainApproachDevice,
  TrainApproachDeviceCreate,
  TrainApproachDeviceListParams,
  TrainApproachDevicePage,
  TrainApproachDeviceUpdate,
} from "@/types";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

// 分页列表（项目/名称模糊/编号精确/状态精确 过滤，按创建时间倒序）
export function fetchTrainApproachDevices(
  params: TrainApproachDeviceListParams,
): Promise<TrainApproachDevicePage> {
  return http<TrainApproachDevicePage>({
    url: "/v1/train-approach-devices",
    method: "GET",
    params,
  });
}

// 详情
export function fetchTrainApproachDevice(id: number): Promise<TrainApproachDevice> {
  return http<TrainApproachDevice>({
    url: `/v1/train-approach-devices/${id}`,
    method: "GET",
  });
}

// 新建
export function createTrainApproachDevice(
  data: TrainApproachDeviceCreate,
): Promise<TrainApproachDevice> {
  return http<TrainApproachDevice>({
    url: "/v1/train-approach-devices",
    method: "POST",
    data,
  });
}

// 更新
export function updateTrainApproachDevice(
  id: number,
  data: TrainApproachDeviceUpdate,
): Promise<TrainApproachDevice> {
  return http<TrainApproachDevice>({
    url: `/v1/train-approach-devices/${id}`,
    method: "PUT",
    data,
  });
}

// 删除（软删）
export function deleteTrainApproachDevice(id: number): Promise<null> {
  return http<null>({
    url: `/v1/train-approach-devices/${id}`,
    method: "DELETE",
  });
}

/** 批量删除列车接近报警设备 */
export function batchDeleteTrainApproachDevices(
  ids: number[],
): Promise<BatchDeleteResult> {
  return batchDelete("/v1/train-approach-devices/batch-delete", ids);
}
