// 媒体展示工具：把后端对象 key（或代理 URL）解析为部门隔离的预签名直连 URL。
//
// 背景（OPTIMIZATION_REPORT #10）：媒体不再匿名公开，前端 <img>/<video> 必须改用
// GET /v1/media/access 返回的 presigned_url（签名直连 MinIO，无需 Authorization 头）。
import { fetchMediaAccess } from "@/api/media";

const MEDIA_PREFIX = "/api/v1/media/";

// 从代理 URL 或裸 key 中提取后端对象 key
export function mediaKeyFromUrl(urlOrKey: string): string {
  const idx = urlOrKey.indexOf(MEDIA_PREFIX);
  if (idx >= 0) {
    return urlOrKey.slice(idx + MEDIA_PREFIX.length).split("?")[0];
  }
  return urlOrKey;
}

// 批量把一组 key/url 解析为 presigned URL；单条失败降级为空串（由组件决定占位）。
// 返回以「原始入参（key/url）」为键的映射，便于模板直接按原值取用。
export async function resolvePresigned(
  keys: string[],
): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  await Promise.all(
    keys.map(async (k) => {
      try {
        const r = await fetchMediaAccess(k);
        out[k] = r.presigned_url || "";
      } catch {
        out[k] = "";
      }
    }),
  );
  return out;
}
