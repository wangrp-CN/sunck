import { http } from "@/utils/request";
import type { Machine, MachinePage, MachineCreate, MachineUpdate, MachineListParams } from "@/types";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

// 机械分页列表（支持 项目/编号/类型 精确过滤，对齐原型《大型机械列表》）
export function fetchMachines(params: MachineListParams): Promise<MachinePage> {
  return http<MachinePage>({
    url: "/v1/machines",
    method: "GET",
    params,
  });
}

// 机械详情
export function fetchMachine(id: number): Promise<Machine> {
  return http<Machine>({
    url: `/v1/machines/${id}`,
    method: "GET",
  });
}

// 新建机械
export function createMachine(data: MachineCreate): Promise<Machine> {
  return http<Machine>({
    url: "/v1/machines",
    method: "POST",
    data,
  });
}

// 更新机械
export function updateMachine(id: number, data: MachineUpdate): Promise<Machine> {
  return http<Machine>({
    url: `/v1/machines/${id}`,
    method: "PUT",
    data,
  });
}

// 删除机械（软删）
export function deleteMachine(id: number): Promise<null> {
  return http<null>({
    url: `/v1/machines/${id}`,
    method: "DELETE",
  });
}

/** 批量删除机械 */
export function batchDeleteMachines(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/machines/batch-delete", ids);
}
