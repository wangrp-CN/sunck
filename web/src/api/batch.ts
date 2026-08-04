/**
 * 批量操作通用客户端。
 *
 * 后端各模块统一提供 `POST {资源前缀}/batch-delete`，请求体 `{ ids: number[] }`，
 * 响应 `{ deleted, total, skipped }`（skipped 为无权访问或已删除而被跳过的条数）。
 */
import { http } from "@/utils/request";

/** 批量删除结果 */
export interface BatchDeleteResult {
  /** 实际删除条数 */
  deleted: number;
  /** 提交的条数 */
  total: number;
  /** 被跳过的条数（不存在/已删除/无权访问/受保护） */
  skipped: number;
}

/** 通用批量删除：由各模块封装具体 URL 后复用 */
export function batchDelete(url: string, ids: number[]): Promise<BatchDeleteResult> {
  return http<BatchDeleteResult>({ url, method: "POST", data: { ids } });
}
