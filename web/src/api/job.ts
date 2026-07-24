// 作业计划 API 封装（三步式：基本信息 → 绑资源 → 绑围栏+规则）
import { http } from "@/utils/request";
import type {
  WorkPlan,
  WorkPlanPage,
  WorkPlanCreate,
  WorkPlanUpdate,
} from "@/types";

// 列表（关键词/项目/状态 过滤）
export function fetchJobs(params?: {
  keyword?: string;
  project_id?: number;
  status?: string;
  is_template?: boolean;
  page?: number;
  size?: number;
}): Promise<WorkPlanPage> {
  return http<WorkPlanPage>({
    url: "/v1/jobs",
    method: "GET",
    params,
  });
}

// 详情（展开绑定）
export function fetchJob(id: number): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: `/v1/jobs/${id}`,
    method: "GET",
  });
}

// 新建（三步式）
export function createJob(req: WorkPlanCreate): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: "/v1/jobs",
    method: "POST",
    data: req,
  });
}

// 更新（含重链绑定）
export function updateJob(
  id: number,
  req: WorkPlanUpdate,
): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: `/v1/jobs/${id}`,
    method: "PUT",
    data: req,
  });
}

// 删除（软删）
export function deleteJob(id: number): Promise<unknown> {
  return http<unknown>({
    url: `/v1/jobs/${id}`,
    method: "DELETE",
  });
}

// 启动作业计划（进入执行中，规则引擎开始判定）
export function startJob(id: number): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: `/v1/jobs/${id}/start`,
    method: "POST",
  });
}

// 完成作业计划（停止规则判定）
export function completeJob(id: number): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: `/v1/jobs/${id}/complete`,
    method: "POST",
  });
}

// 激活中的作业计划（规则引擎据此判定，供大屏/监控联动）
export function fetchActiveJobs(params?: {
  project_id?: number;
}): Promise<WorkPlan[]> {
  return http<WorkPlan[]>({
    url: "/v1/jobs/active",
    method: "GET",
    params,
  });
}

// 根据围栏查询关联的作业计划（地图围栏点击 → 计划详情弹层）
// 一个围栏可关联多个作业计划（不同阶段/单位的监护计划）。
export function fetchJobsByFence(fenceId: number): Promise<WorkPlan[]> {
  return http<WorkPlan[]>({
    url: `/v1/jobs/by-fence/${fenceId}`,
    method: "GET",
  });
}

// 克隆作业计划（深拷贝绑定，执行态清零为草稿/未激活）
export function cloneJob(id: number): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: `/v1/jobs/${id}/clone`,
    method: "POST",
  });
}

// 将作业计划存为模板（深拷贝绑定，标记 is_template=true）
export function saveJobAsTemplate(id: number): Promise<WorkPlan> {
  return http<WorkPlan>({
    url: `/v1/jobs/${id}/save-as-template`,
    method: "POST",
  });
}

// 模板库：仅列出 is_template=true 的计划
export function fetchJobTemplates(params?: {
  project_id?: number;
  page?: number;
  size?: number;
}): Promise<WorkPlanPage> {
  return http<WorkPlanPage>({
    url: "/v1/jobs",
    method: "GET",
    params: { is_template: true, ...(params || {}) },
  });
}
