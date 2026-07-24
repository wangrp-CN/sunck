// 巡检打卡 API（P3·⑨）
import { http } from "@/utils/request";
import type {
  InspectionTask,
  InspectionTaskPage,
  InspectionStats,
} from "@/types";

// 巡检统计
export function fetchInspectionStats(): Promise<InspectionStats> {
  return http<InspectionStats>({
    url: "/v1/inspections/stats",
    method: "GET",
  });
}

// 任务列表（筛选+分页）
export function fetchInspectionTasks(params?: {
  project_id?: number;
  status?: string;
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<InspectionTaskPage> {
  return http<InspectionTaskPage>({
    url: "/v1/inspections",
    method: "GET",
    params,
  });
}

// 任务详情（含打卡记录）
export function fetchInspectionTask(id: number): Promise<InspectionTask> {
  return http<InspectionTask>({
    url: `/v1/inspections/${id}`,
    method: "GET",
  });
}

// 创建任务
export function createInspectionTask(req: {
  project_id?: number | null;
  name: string;
  content?: string | null;
  assignee_id?: number | null;
  start_time?: string | null;
  end_time?: string | null;
  required_checkins?: number;
}): Promise<InspectionTask> {
  return http<InspectionTask>({
    url: "/v1/inspections",
    method: "POST",
    data: req,
  });
}

// 更新任务
export function updateInspectionTask(
  id: number,
  req: {
    project_id?: number | null;
    name?: string;
    content?: string | null;
    assignee_id?: number | null;
    start_time?: string | null;
    end_time?: string | null;
    required_checkins?: number;
  },
): Promise<InspectionTask> {
  return http<InspectionTask>({
    url: `/v1/inspections/${id}`,
    method: "PUT",
    data: req,
  });
}

// 删除任务（软删）
export function deleteInspectionTask(id: number): Promise<unknown> {
  return http<unknown>({
    url: `/v1/inspections/${id}`,
    method: "DELETE",
  });
}

// 状态流转 start/finish/cancel
export function transitionInspectionTask(
  id: number,
  action: "start" | "finish" | "cancel",
): Promise<InspectionTask> {
  return http<InspectionTask>({
    url: `/v1/inspections/${id}/transition`,
    method: "POST",
    data: { action },
  });
}

// 打卡
export function checkinInspectionTask(
  id: number,
  req: {
    checkin_by_name?: string | null;
    lng?: number | null;
    lat?: number | null;
    result?: string;
    note?: string | null;
  },
): Promise<unknown> {
  return http<unknown>({
    url: `/v1/inspections/${id}/checkin`,
    method: "POST",
    data: req,
  });
}

// 异常打卡转隐患（巡检→治理闭环）
export function convertCheckinToHazard(recordId: number): Promise<{ hazard_id: number }> {
  return http<{ hazard_id: number }>({
    url: `/v1/inspections/records/${recordId}/convert-to-hazard`,
    method: "POST",
  });
}
