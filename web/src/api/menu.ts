/** 菜单管理 API 封装。
 *
 * 菜单基于 Permission 模型，type=1(目录) / 2(菜单项) / 3(按钮/接口)。
 * 菜单管理页管理全部类型；导航渲染请使用 fetchMenuTree()，它仅返回启用状态的目录和菜单。
 */
import { http } from "@/utils/request";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

export interface MenuItem {
  id: number;
  name: string;
  code: string;
  type: number; // 1=目录 2=菜单 3=按钮
  parent_id: number | null;
  path: string | null;
  component: string | null;
  icon: string | null;
  sort: number;
  status: boolean;
  redirect: string | null;
  is_hidden: boolean;
  is_cache: boolean;
  is_affix: boolean;
  is_external: boolean;
  remark: string | null;
  is_deleted: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface MenuTreeItem extends MenuItem {
  children: MenuTreeItem[];
}

export interface MenuCreate {
  name: string;
  code: string;
  type: number;
  parent_id?: number | null;
  path?: string | null;
  component?: string | null;
  icon?: string | null;
  sort?: number;
  status?: boolean;
  redirect?: string | null;
  is_hidden?: boolean;
  is_cache?: boolean;
  is_affix?: boolean;
  is_external?: boolean;
  remark?: string | null;
}

export interface MenuUpdate {
  name?: string | null;
  code?: string | null;
  type?: number | null;
  parent_id?: number | null;
  path?: string | null;
  component?: string | null;
  icon?: string | null;
  sort?: number | null;
  status?: boolean | null;
  redirect?: string | null;
  is_hidden?: boolean | null;
  is_cache?: boolean | null;
  is_affix?: boolean | null;
  is_external?: boolean | null;
  remark?: string | null;
}

export interface MenuQuery {
  keyword?: string;
  type?: number | null;
  status?: boolean | null;
}

// ── 查询 ──

export function fetchMenus(params: MenuQuery = {}): Promise<MenuTreeItem[]> {
  return http<MenuTreeItem[]>({ url: "/v1/menus", method: "GET", params });
}

export function fetchMenuTree(): Promise<MenuTreeItem[]> {
  return http<MenuTreeItem[]>({ url: "/v1/menus/tree", method: "GET" });
}

export function fetchMenuOptions(): Promise<MenuItem[]> {
  return http<MenuItem[]>({ url: "/v1/menus/options", method: "GET" });
}

export function fetchMenu(id: number): Promise<MenuItem> {
  return http<MenuItem>({ url: `/v1/menus/${id}`, method: "GET" });
}

// ── 写入 ──

export function createMenu(data: MenuCreate): Promise<MenuItem> {
  return http<MenuItem>({ url: "/v1/menus", method: "POST", data });
}

export function updateMenu(id: number, data: MenuUpdate): Promise<MenuItem> {
  return http<MenuItem>({ url: `/v1/menus/${id}`, method: "PUT", data });
}

export function deleteMenu(id: number): Promise<null> {
  return http<null>({ url: `/v1/menus/${id}`, method: "DELETE" });
}

// ── 批量 ──

export function batchDeleteMenus(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/menus/batch-delete", ids);
}
