import { http } from "@/utils/request";
import type { DashboardStats, RecentAlarm } from "@/types";
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
