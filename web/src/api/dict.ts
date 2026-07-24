// 数据字典 API 封装
import { http } from "@/utils/request";

export interface DictItem {
  id: number;
  type_code: string;
  label: string;
  value: string;
  sort: number;
  enabled: boolean;
  remark: string | null;
  ext: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DictType {
  id: number;
  code: string;
  name: string;
  description: string | null;
  system: boolean;
  items: DictItem[];
  created_at: string | null;
  updated_at: string | null;
}

export interface DictTypePage {
  total: number;
  items: DictType[];
  page: number;
  size: number;
}

export interface DictTypeCreate {
  code: string;
  name: string;
  description?: string | null;
  items?: DictItemCreate[];
}

export interface DictItemCreate {
  label: string;
  value: string;
  sort?: number;
  enabled?: boolean;
  remark?: string | null;
  ext?: string | null;
}

export type DictItemUpdate = Partial<DictItemCreate>;

// 字典类型列表
export function fetchDictTypes(params: {
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<DictTypePage> {
  return http<DictTypePage>({ url: "/v1/dicts", method: "get", params });
}

// 类型详情
export function fetchDictType(code: string): Promise<DictType> {
  return http<DictType>({ url: `/v1/dicts/${code}`, method: "get" });
}

// 创建字典类型
export function createDictType(payload: DictTypeCreate): Promise<DictType> {
  return http<DictType>({ url: "/v1/dicts", method: "post", data: payload });
}

// 更新字典类型
export function updateDictType(
  code: string,
  payload: { name?: string; description?: string | null },
): Promise<DictType> {
  return http<DictType>({ url: `/v1/dicts/${code}`, method: "put", data: payload });
}

// 删除字典类型
export async function deleteDictType(code: string): Promise<void> {
  await http({ url: `/v1/dicts/${code}`, method: "delete" });
}

// 字典项列表（enabledOnly=true 供业务下拉引用）
export function fetchDictItems(code: string, enabledOnly = false): Promise<DictItem[]> {
  return http<DictItem[]>({
    url: `/v1/dicts/${code}/items`,
    method: "get",
    params: { enabled_only: enabledOnly },
  });
}

// 新增字典项
export function createDictItem(code: string, payload: DictItemCreate): Promise<DictItem> {
  return http<DictItem>({ url: `/v1/dicts/${code}/items`, method: "post", data: payload });
}

// 更新字典项
export function updateDictItem(itemId: number, payload: DictItemUpdate): Promise<DictItem> {
  return http<DictItem>({ url: `/v1/dicts/items/${itemId}`, method: "put", data: payload });
}

// 删除字典项
export async function deleteDictItem(itemId: number): Promise<void> {
  await http({ url: `/v1/dicts/items/${itemId}`, method: "delete" });
}
