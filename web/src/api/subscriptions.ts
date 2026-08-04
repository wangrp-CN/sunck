// 定期订阅推送前端接口 (#①·报告与触达增强)，与后端 app/api/v1/subscriptions.py 对齐。
import { ElMessage } from "element-plus";
import request from "@/utils/request";
import { http } from "@/utils/request";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

export type SubFrequency = "daily" | "weekly" | "monthly";
export type SubFormat = "excel" | "pdf";

// 订阅记录（对齐 ReportSubscription.to_dict）
export interface ReportSubscription {
  id: number;
  user_id: number;
  name: string;
  fmt: SubFormat;
  days: number;
  project_id: number | null;
  frequency: SubFrequency;
  send_hour: number;
  send_weekday: number;
  send_day: number;
  channels: string[];
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

// 订阅分页结果
export interface SubscriptionPage {
  items: ReportSubscription[];
  total: number;
  page: number;
  size: number;
}

export interface SubscriptionCreate {
  name: string;
  fmt?: SubFormat;
  days?: number;
  project_id?: number | null;
  frequency?: SubFrequency;
  send_hour?: number;
  send_weekday?: number;
  send_day?: number;
  channels?: string[];
  enabled?: boolean;
}

export type SubscriptionUpdate = Partial<SubscriptionCreate>;

export interface TriggerResult {
  id: number;
  status: string;
  bytes: number;
  media_type: string;
  filename: string;
}

// 列表（分页；超管传 all=true 看全部）
export function listSubscriptions(params: {
  page: number;
  size: number;
  all?: boolean;
}): Promise<SubscriptionPage> {
  return http<SubscriptionPage>({
    url: "/v1/subscriptions",
    method: "GET",
    params: {
      page: params.page,
      size: params.size,
      ...(params.all ? { all: true } : {}),
    },
  });
}

// 批量删除订阅
export function batchDeleteSubscriptions(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/subscriptions/batch-delete", ids);
}

export function createSubscription(payload: SubscriptionCreate): Promise<ReportSubscription> {
  return http<ReportSubscription>({ url: "/v1/subscriptions", method: "POST", data: payload });
}

export function updateSubscription(
  id: number,
  payload: SubscriptionUpdate,
): Promise<ReportSubscription> {
  return http<ReportSubscription>({ url: `/v1/subscriptions/${id}`, method: "PUT", data: payload });
}

export function deleteSubscription(id: number): Promise<void> {
  return http<void>({ url: `/v1/subscriptions/${id}`, method: "DELETE" });
}

export function triggerSubscription(id: number): Promise<TriggerResult> {
  return http<TriggerResult>({ url: `/v1/subscriptions/${id}/trigger`, method: "POST" });
}

// 下载报告（二进制流）。失败经 ElMessage 提示，返回 void。
export async function downloadSubscription(id: number): Promise<void> {
  const resp = await request.get(`/v1/subscriptions/${id}/download`, { responseType: "blob" });
  const ct = (resp.headers["content-type"] || "") as string;
  if (ct.includes("application/json")) {
    const text = await (resp.data as Blob).text();
    let msg = "下载失败";
    try {
      const j = JSON.parse(text);
      msg = j.message || msg;
    } catch {
      /* 忽略解析失败 */
    }
    ElMessage.error(msg);
    return;
  }
  const disp = (resp.headers["content-disposition"] || "") as string;
  const m = disp.match(/filename\*=UTF-8''([^;]+)/) || disp.match(/filename="?([^";]+)"?/);
  const filename = m ? decodeURIComponent(m[1]) : `subscription_${id}`;
  const url = URL.createObjectURL(resp.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
