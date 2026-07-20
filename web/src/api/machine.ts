import { http } from "@/utils/request";
import type { Machine, MachinePage, MachineCreate, MachineUpdate } from "@/types";

// 机械分页列表
export function fetchMachines(params: {
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<MachinePage> {
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
