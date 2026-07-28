// 设备指令下发记录接口（闭环追踪：列表 / 详情 / 重试）
import { http } from "@/utils/request";
import type { DeviceCommand } from "@/types";

export interface CommandListResp {
  items: DeviceCommand[];
  total: number;
  page: number;
  size: number;
}

export function listCommands(params: {
  device_no?: string;
  device_type?: string;
  status?: string;
  alarm_id?: number;
  page?: number;
  size?: number;
}): Promise<CommandListResp> {
  return http<CommandListResp>({
    url: "/v1/commands",
    method: "GET",
    params,
  });
}

export function retryCommand(id: number): Promise<DeviceCommand> {
  return http<DeviceCommand>({
    url: `/v1/commands/${id}/retry`,
    method: "POST",
  });
}
