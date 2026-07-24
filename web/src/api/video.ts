// 视频 AI API（P3·⑧ PoC）
import { http } from "@/utils/request";
import type { VideoChannel, VideoEvent } from "@/types";

// 通道列表
export function fetchVideoChannels(params?: {
  project_id?: number;
  keyword?: string;
}): Promise<VideoChannel[]> {
  return http<VideoChannel[]>({
    url: "/v1/videos/channels",
    method: "GET",
    params,
  });
}

// 创建通道
export function createVideoChannel(req: {
  project_id?: number | null;
  name: string;
  channel_no: string;
  stream_url?: string | null;
  vendor?: string | null;
  location_desc?: string | null;
  lng?: number | null;
  lat?: number | null;
  status?: string;
  ai_enabled?: boolean;
}): Promise<VideoChannel> {
  return http<VideoChannel>({
    url: "/v1/videos/channels",
    method: "POST",
    data: req,
  });
}

// 更新通道
export function updateVideoChannel(
  id: number,
  req: {
    project_id?: number | null;
    name?: string;
    stream_url?: string | null;
    vendor?: string | null;
    location_desc?: string | null;
    lng?: number | null;
    lat?: number | null;
    status?: string;
    ai_enabled?: boolean;
  },
): Promise<VideoChannel> {
  return http<VideoChannel>({
    url: `/v1/videos/channels/${id}`,
    method: "PUT",
    data: req,
  });
}

// 删除通道
export function deleteVideoChannel(id: number): Promise<unknown> {
  return http<unknown>({
    url: `/v1/videos/channels/${id}`,
    method: "DELETE",
  });
}

// AI 事件列表（按可见通道过滤）
export function fetchVideoEvents(params?: {
  project_id?: number;
  channel_id?: number;
  handled?: boolean;
  limit?: number;
}): Promise<VideoEvent[]> {
  return http<VideoEvent[]>({
    url: "/v1/videos/events",
    method: "GET",
    params,
  });
}

// 处理事件
export function handleVideoEvent(id: number): Promise<unknown> {
  return http<unknown>({
    url: `/v1/videos/events/${id}/handle`,
    method: "POST",
  });
}
