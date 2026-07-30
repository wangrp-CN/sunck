// 知识库 API 封装（🅱 知识库自动检索关联链接）
// 后端路由前缀 /v1/knowledge：
//   GET    /search      相关性检索（knowledge:list）
//   GET    /            分页列表（knowledge:list）
//   GET    /{id}        详情（knowledge:list）
//   POST   /            新增（knowledge:manage）
//   PUT    /{id}        编辑（knowledge:manage）
//   DELETE /{id}        删除（knowledge:manage，逻辑）
// 约定：http<T> 已解包 data，失败时抛 Error(message)。
import { http } from "@/utils/request";

/** 知识库条目 */
export interface KnowledgeArticle {
  id: number;
  title: string;
  url: string;
  summary: string;
  source: string;
  tags: string | null;
  content: string | null;
  project_id: number | null;
  project_name: string | null;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** 检索命中项（含相关性分数） */
export interface KnowledgeSearchItem extends KnowledgeArticle {
  score: number;
}

/** 分页列表 */
export interface KnowledgePage {
  total: number;
  items: KnowledgeArticle[];
  page: number;
  size: number;
}

/** 检索参数 */
export interface KnowledgeSearchParams {
  q: string;
  limit?: number;
}

/** 列表查询参数 */
export interface KnowledgeListParams {
  project_id?: number;
  source?: string;
  enabled?: boolean;
  page?: number;
  size?: number;
}

/** 新建/编辑表单 */
export interface KnowledgePayload {
  title: string;
  url: string;
  summary: string;
  source?: string;
  tags?: string | null;
  content?: string | null;
  project_id?: number | null;
  enabled?: boolean;
}

export function searchKnowledge(params: KnowledgeSearchParams): Promise<KnowledgeSearchItem[]> {
  return http<KnowledgeSearchItem[]>({
    url: "/v1/knowledge/search",
    method: "GET",
    params: { q: params.q, limit: params.limit ?? 10 },
  });
}

export function listKnowledge(params: KnowledgeListParams): Promise<KnowledgePage> {
  return http<KnowledgePage>({ url: "/v1/knowledge/", method: "GET", params });
}

export function getKnowledge(id: number): Promise<KnowledgeArticle> {
  return http<KnowledgeArticle>({ url: `/v1/knowledge/${id}`, method: "GET" });
}

export function createKnowledge(data: KnowledgePayload): Promise<KnowledgeArticle> {
  return http<KnowledgeArticle>({ url: "/v1/knowledge/", method: "POST", data });
}

export function updateKnowledge(
  id: number,
  data: Partial<KnowledgePayload>,
): Promise<KnowledgeArticle> {
  return http<KnowledgeArticle>({ url: `/v1/knowledge/${id}`, method: "PUT", data });
}

export function deleteKnowledge(id: number): Promise<{ deleted: boolean }> {
  return http<{ deleted: boolean }>({ url: `/v1/knowledge/${id}`, method: "DELETE" });
}
