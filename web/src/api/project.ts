import { http } from "@/utils/request";
import type { Project, ProjectPage, ProjectCreate, ProjectUpdate } from "@/types";

// 项目分页列表
export function fetchProjects(params: {
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<ProjectPage> {
  return http<ProjectPage>({
    url: "/v1/projects",
    method: "GET",
    params,
  });
}

// 项目详情
export function fetchProject(id: number): Promise<Project> {
  return http<Project>({
    url: `/v1/projects/${id}`,
    method: "GET",
  });
}

// 新建项目
export function createProject(data: ProjectCreate): Promise<Project> {
  return http<Project>({
    url: "/v1/projects",
    method: "POST",
    data,
  });
}

// 更新项目
export function updateProject(id: number, data: ProjectUpdate): Promise<Project> {
  return http<Project>({
    url: `/v1/projects/${id}`,
    method: "PUT",
    data,
  });
}

// 删除项目（软删）
export function deleteProject(id: number): Promise<null> {
  return http<null>({
    url: `/v1/projects/${id}`,
    method: "DELETE",
  });
}
