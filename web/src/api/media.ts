// 媒体管理 API 封装（上传 / 预签名 / 告警媒体挂载）
import { http } from "@/utils/request";
import type { MediaMeta } from "@/types";

// 上传媒体文件（多文件），prefix 用于业务归类（如 alarms/123）
// 返回 MediaMeta[]（已解包 data）
export function uploadMedia(files: File[] | FileList, prefix = ""): Promise<MediaMeta[]> {
  const form = new FormData();
  const list = Array.from(files as ArrayLike<File>);
  list.forEach((f) => form.append("files", f));
  if (prefix) form.append("prefix", prefix);
  return http<MediaMeta[]>({
    url: "/v1/media/upload",
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
  });
}

// 获取预签名 URL（可选，便于直连 MinIO）
export function presignedMedia(
  key: string,
  expiry = 3600,
): Promise<{ key: string; url: string; presigned_url: string }> {
  return http({
    url: "/v1/media/presigned",
    method: "GET",
    params: { key, expiry },
  });
}

// 获取部门隔离的预签名媒体 URL（前端 <img>/<video> 展示用，取代匿名代理 URL）
export function fetchMediaAccess(
  key: string,
): Promise<{ key: string; presigned_url: string }> {
  return http({
    url: "/v1/media/access",
    method: "GET",
    params: { key },
  });
}

// 整体替换某告警的媒体 URL 列表，返回更新后的列表
export function putAlarmMedia(
  alarmId: number,
  urls: string[],
): Promise<{ id: number; media_urls: string[] }> {
  return http({
    url: `/v1/alarms/${alarmId}/media`,
    method: "PUT",
    data: { urls },
  });
}
