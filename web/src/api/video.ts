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
  event_type?: string;
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

// 升级为平台告警（闭环联动⑧）：回填 alarm_id，闭合「监测→异常→告警」
export function escalateVideoEvent(
  id: number,
): Promise<{ event_id: number; alarm_id: number | null; alarm_level?: string | null }> {
  return http<{ event_id: number; alarm_id: number | null; alarm_level?: string | null }>({
    url: `/v1/videos/events/${id}/escalate`,
    method: "POST",
  });
}

// 视频 AI 可识别能力清单（深化⑧）
export function fetchVideoAiCapabilities(): Promise<{ capabilities: string[] }> {
  return http<{ capabilities: string[] }>({
    url: "/v1/videos/ai/capabilities",
    method: "GET",
  });
}

// 视频 AI 异常识别（深化⑧）：对指定通道/帧发起分析，支持外部推理服务返回 findings
export function analyzeVideo(req: {
  channel_no?: string | null;
  frame_url?: string | null;
  model?: string | null;
}): Promise<VideoAiAnalyzeResult> {
  return http<VideoAiAnalyzeResult>({
    url: "/v1/videos/ai/analyze",
    method: "POST",
    data: req,
  });
}
