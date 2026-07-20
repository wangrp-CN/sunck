import { http } from "@/utils/request";
import type { Fence, FencePage, FenceCreate, FenceUpdate } from "@/types";

// 围栏分页列表
export function fetchFences(params: {
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<FencePage> {
  return http<FencePage>({
    url: "/v1/fences",
    method: "GET",
    params,
  });
}

// 围栏详情
export function fetchFence(id: number): Promise<Fence> {
  return http<Fence>({
    url: `/v1/fences/${id}`,
    method: "GET",
  });
}

// 新建围栏
export function createFence(data: FenceCreate): Promise<Fence> {
  return http<Fence>({
    url: "/v1/fences",
    method: "POST",
    data,
  });
}

// 更新围栏
export function updateFence(id: number, data: FenceUpdate): Promise<Fence> {
  return http<Fence>({
    url: `/v1/fences/${id}`,
    method: "PUT",
    data,
  });
}

// 删除围栏（软删）
export function deleteFence(id: number): Promise<null> {
  return http<null>({
    url: `/v1/fences/${id}`,
    method: "DELETE",
  });
}
