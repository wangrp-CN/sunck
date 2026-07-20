import { http } from "@/utils/request";
import type { Department, DepartmentCreate, DepartmentUpdate } from "@/types";

// 部门列表（扁平）
export function fetchDepartments(keyword?: string): Promise<Department[]> {
  return http<Department[]>({
    url: "/v1/departments",
    method: "GET",
    params: keyword ? { keyword } : undefined,
  });
}

// 部门树形
export function fetchDepartmentTree(): Promise<Department[]> {
  return http<Department[]>({ url: "/v1/departments/tree", method: "GET" });
}

// 新建部门
export function createDepartment(data: DepartmentCreate): Promise<Department> {
  return http<Department>({ url: "/v1/departments", method: "POST", data });
}

// 编辑部门
export function updateDepartment(
  id: number,
  data: DepartmentUpdate,
): Promise<Department> {
  return http<Department>({ url: `/v1/departments/${id}`, method: "PUT", data });
}

// 删除部门（软删）
export function deleteDepartment(id: number): Promise<null> {
  return http<null>({ url: `/v1/departments/${id}`, method: "DELETE" });
}
