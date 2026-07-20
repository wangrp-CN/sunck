import { http } from "@/utils/request";
import type { Permission } from "@/types";

// 权限列表（前端用于角色-权限分配）
export function listPermissions(): Promise<Permission[]> {
  return http<Permission[]>({ url: "/v1/auth/permissions", method: "GET" });
}
