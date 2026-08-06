import request, { http } from "@/utils/request";
import type {
  DashboardStats,
  RecentAlarm,
  ProjectCompareResp,
  Effectiveness,
} from "@/types";
import type { Granularity } from "@/api/alarm";

// 监控大屏聚合统计（支持周期联动：传 granularity + 时间窗）
export function getDashboardStats(params?: {
  granularity?: Granularity;
  start?: string;
  end?: string;
}): Promise<DashboardStats> {
  return http<DashboardStats>({
    url: "/v1/dashboard/stats",
    method: "GET",
    params: params || {},
  });
}

// 最近告警流（大屏滚动）
export function getRecentAlarms(
  limit = 20,
): Promise<{ items: RecentAlarm[]; total: number }> {
  return http<{ items: RecentAlarm[]; total: number }>({
    url: "/v1/dashboard/recent-alarms",
    method: "GET",
    params: { limit },
  });
}

// 多项目横向对比大屏（P3·⑪）：按风险分降序
export function getProjectCompare(days = 7): Promise<ProjectCompareResp> {
  return http<ProjectCompareResp>({
    url: "/v1/dashboard/project-compare",
    method: "GET",
    params: { days },
  });
}

// 闭环效能度量（监测→异常→告警→派单→治理全链路有效性）
export function getEffectiveness(
  days = 30,
  projectId: number | null = null,
): Promise<Effectiveness> {
  return http<Effectiveness>({
    url: "/v1/dashboard/effectiveness",
    method: "GET",
    params: projectId ? { days, project_id: projectId } : { days },
  });
}

// 导出闭环效能运营报告（按项目维度，excel|pdf）——返回二进制 Blob，不走 http<T> 解包
export function exportEffectivenessReport(
  fmt: "excel" | "pdf",
  params: { days?: number; projectId?: number | null },
): Promise<Blob> {
  return request
    .get("/v1/dashboard/effectiveness/export", {
      params: {
        fmt,
        days: params.days ?? 30,
        ...(params.projectId != null ? { project_id: params.projectId } : {}),
      },
      responseType: "blob",
    })
    .then((r) => r.data as Blob);
}

// 单项目 5 指标复合趋势大图（PNG Blob，供效能看板「趋势大图」弹窗）
export function getProjectTrendImage(params: {
  projectId: number;
  days?: number;
  mode?: "large" | "small";
}): Promise<Blob> {
  return request
    .get("/v1/dashboard/effectiveness/project-trend-image", {
      params: {
        project_id: params.projectId,
        days: params.days ?? 30,
        mode: params.mode ?? "large",
      },
      responseType: "blob",
    })
    .then((r) => r.data as Blob);
}
