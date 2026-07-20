import { http } from "@/utils/request";
import type { SysUser, UserPage, UserCreate, UserUpdate } from "@/types";

// 用户列表（分页 + 关键字）
export function listUsers(params?: {
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<UserPage> {
  return http<UserPage>({ url: "/v1/auth/users", method: "GET", params });
}

// 新建用户（管理员）
export function createUser(data: UserCreate): Promise<SysUser> {
  return http<SysUser>({ url: "/v1/auth/register", method: "POST", data });
}

// 编辑用户
export function updateUser(id: number, data: UserUpdate): Promise<SysUser> {
  return http<SysUser>({ url: `/v1/auth/users/${id}`, method: "PUT", data });
}

// 删除用户（软删）
export function deleteUser(id: number): Promise<null> {
  return http<null>({ url: `/v1/auth/users/${id}`, method: "DELETE" });
}
