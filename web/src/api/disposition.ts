// 告警处置记录（处置效果闭环）前端接口
// 与后端 app/api/v1/dispositions.py 对齐：
// - GET  /v1/dispositions          处置记录列表（项目/处置人/结果/时间窗过滤 + 分页）
// - GET  /v1/dispositions/stats    处置效能统计（闭环率、平均处置时长、按处置人/项目/结果分布）
// - GET  /v1/alarms/{id}/dispositions  单告警处置记录
import { http } from "@/utils/request";

// 单条处置记录（与 AlarmView 共用，避免循环依赖这里重新声明精简结构）
export interface DispositionOut {
  id: number;
  alarm_id: number;
  project_id: number | null;
  handler_id: number | null;
  playbook_id: number | null;
  knowledge_refs: { title: string; url: string }[];
  outcome: string | null;
  action_taken: string | null;
  note: string | null;
  resolved_at: string | null;
  created_at: string | null;
}

// 处置效能统计（与后端 disposition_service.disposition_stats 返回值对齐）
export interface DispositionStats {
  period_days: number;
  total: number;
  resolved: number;
  closure_rate: number | null;
  avg_duration_hours: number | null;
  by_outcome: Record<string, number>;
  by_handler: {
    handler_id: number;
    total: number;
    resolved: number;
    closure_rate: number | null;
  }[];
  by_project: {
    project_id: number;
    total: number;
    resolved: number;
    closure_rate: number | null;
  }[];
}

// 处置效能统计（闭环率、平均处置时长、按处置人/项目/结果分布）
export function getDispositionStats(params: {
  days?: number;
  project_id?: number;
} = {}): Promise<DispositionStats> {
  return http<DispositionStats>({ url: "/v1/dispositions/stats", method: "GET", params });
}
