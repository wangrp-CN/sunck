import { http } from "@/utils/request";
import type { Role, RoleCreate, RoleUpdate } from "@/types";

// 角色列表
export function listRoles(): Promise<Role[]> {
  return http<Role[]>({ url: "/v1/auth/roles", method: "GET" });
}

// 新建角色
export function createRole(data: RoleCreate): Promise<Role> {
  return http<Role>({ url: "/v1/auth/roles", method: "POST", data });
}

// 编辑角色
export function updateRole(id: number, data: RoleUpdate): Promise<Role> {
  return http<Role>({ url: `/v1/auth/roles/${id}`, method: "PUT", data });
}

// 删除角色
export function deleteRole(id: number): Promise<null> {
  return http<null>({ url: `/v1/auth/roles/${id}`, method: "DELETE" });
}

// 分配角色权限（全量覆盖）
export function assignRolePermissions(
  id: number,
  permission_codes: string[],
): Promise<Role> {
  return http<Role>({
    url: `/v1/auth/roles/${id}/permissions`,
    method: "POST",
    data: { permission_codes },
  });
}

// 分配角色自定义数据范围部门（data_scope=2，全量覆盖）
export function assignRoleDepartments(
  id: number,
  dept_ids: number[],
): Promise<Role> {
  return http<Role>({
    url: `/v1/auth/roles/${id}/departments`,
    method: "POST",
    data: { dept_ids },
  });
}
