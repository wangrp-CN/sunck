import { http } from "@/utils/request";
import type {
  Project,
  ProjectListParams,
  ProjectPage,
  ProjectCreate,
  ProjectUpdate,
} from "@/types";

// 项目分页列表（支持归属部门 / 名称 / 开工 / 完工日期区间 / 状态过滤）
export function fetchProjects(params: ProjectListParams): Promise<ProjectPage> {
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
