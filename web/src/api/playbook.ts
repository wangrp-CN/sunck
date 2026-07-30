// 处置预案（知识库）API 封装（🅱 M5 处置预案/知识库联动）
// 后端路由前缀 /v1/playbooks：
//   GET    /                 分页列表（playbook:list）
//   GET    /meta             枚举选项（playbook:list）
//   GET    /recommend        按 (project_id,alarm_type,alarm_level) 推荐（playbook:list）
//   GET    /recommend-by-alarm/{id} 按告警 ID 推荐（playbook:list）
//   GET    /{id}             详情（playbook:list）
//   POST   /                 新增（playbook:manage）
//   PUT    /{id}             编辑（playbook:manage）
//   DELETE /{id}             删除（逻辑，playbook:manage）
// 约定：http<T> 已解包 data，失败时抛 Error(message)。
import { http } from "@/utils/request";

/** 知识库链接 */
export interface PlaybookRef {
  title: string;
  url: string;
}

/** 单条处置预案（与后端 PlaybookOut 对齐） */
export interface Playbook {
  id: number;
  name: string;
  project_id: number | null;
  project_name: string | null;
  alarm_type: string | null;
  alarm_level: string | null;
  enabled: boolean;
  summary: string;
  steps: string[];
  trigger_condition: string | null;
  references: PlaybookRef[];
  tags: string | null;
  owner_role: string | null;
  est_minutes: number | null;
  note: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 分页列表 */
export interface PlaybookPage {
  total: number;
  items: Playbook[];
  page: number;
  size: number;
}

/** 枚举元数据 */
export interface PlaybookMeta {
  alarm_types: { key: string; label: string }[];
  levels: string[];
}

/** 推荐查询参数 */
export interface PlaybookRecommendParams {
  project_id?: number;
  alarm_type?: string;
  alarm_level?: string;
  limit?: number;
}

/** 列表查询参数 */
export interface PlaybookListParams {
  project_id?: number;
  alarm_type?: string;
  alarm_level?: string;
  enabled?: boolean;
  page?: number;
  size?: number;
}

/** 新建/编辑表单（project_id 为空=全局；alarm_type 为空=通配；
 *  alarm_level 为空=不限；steps/references 以数组提交） */
export interface PlaybookPayload {
  name: string;
  project_id?: number | null;
  alarm_type?: string | null;
  alarm_level?: string | null;
  enabled?: boolean;
  summary: string;
  steps?: string[];
  trigger_condition?: string | null;
  references?: PlaybookRef[];
  tags?: string | null;
  owner_role?: string | null;
  est_minutes?: number | null;
  note?: string | null;
}

export function getPlaybookMeta(): Promise<PlaybookMeta> {
  return http<PlaybookMeta>({ url: "/v1/playbooks/meta", method: "GET" });
}

export function listPlaybooks(params: PlaybookListParams): Promise<PlaybookPage> {
  return http<PlaybookPage>({ url: "/v1/playbooks/", method: "GET", params });
}

export function getPlaybook(id: number): Promise<Playbook> {
  return http<Playbook>({ url: `/v1/playbooks/${id}`, method: "GET" });
}

export function recommendPlaybooks(params: PlaybookRecommendParams): Promise<Playbook[]> {
  return http<Playbook[]>({ url: "/v1/playbooks/recommend", method: "GET", params });
}

export function recommendPlaybooksByAlarm(
  alarmId: number,
  limit = 5,
): Promise<Playbook[]> {
  return http<Playbook[]>({
    url: `/v1/playbooks/recommend-by-alarm/${alarmId}`,
    method: "GET",
    params: { limit },
  });
}

export function createPlaybook(data: PlaybookPayload): Promise<Playbook> {
  return http<Playbook>({ url: "/v1/playbooks/", method: "POST", data });
}

export function updatePlaybook(
  id: number,
  data: Partial<PlaybookPayload>,
): Promise<Playbook> {
  return http<Playbook>({ url: `/v1/playbooks/${id}`, method: "PUT", data });
}

export function deletePlaybook(id: number): Promise<{ deleted: boolean }> {
  return http<{ deleted: boolean }>({ url: `/v1/playbooks/${id}`, method: "DELETE" });
}
