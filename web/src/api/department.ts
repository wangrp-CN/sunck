import { http } from "@/utils/request";
import type {
  Department,
  DepartmentCreate,
  DepartmentPage,
  DepartmentTree,
  DepartmentUpdate,
} from "@/types";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

// 部门列表（扁平，供下拉消费）
export function fetchDepartments(keyword?: string): Promise<Department[]> {
  return http<Department[]>({
    url: "/v1/departments",
    method: "GET",
    params: keyword ? { keyword } : undefined,
  });
}

// 部门列表（分页，供部门管理页）
export function fetchDepartmentsPage(params: {
  page: number;
  size: number;
  keyword?: string;
}): Promise<DepartmentPage> {
  return http<DepartmentPage>({
    url: "/v1/departments/page",
    method: "GET",
    params: { page: params.page, size: params.size, keyword: params.keyword || undefined },
  });
}

// 批量删除部门
export function batchDeleteDepartments(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/departments/batch-delete", ids);
}

// 部门树形
export function fetchDepartmentTree(): Promise<DepartmentTree[]> {
  return http<DepartmentTree[]>({ url: "/v1/departments/tree", method: "GET" });
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
