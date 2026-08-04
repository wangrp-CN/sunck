// 地图资源库 API 封装
import { http } from "@/utils/request";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

export type MapAssetType =
  | "station_plan"
  | "plan_image"
  | "satellite"
  | "custom_basemap";

export interface MapAsset {
  id: number;
  name: string;
  type: MapAssetType;
  project_id: number | null;
  center_lng: number | null;
  center_lat: number | null;
  zoom: number | null;
  coverage_wkt: string | null;
  image_url: string | null;
  remark: string | null;
  operator: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MapAssetPage {
  total: number;
  items: MapAsset[];
  page: number;
  size: number;
}

export interface MapAssetCreate {
  name: string;
  type: MapAssetType;
  project_id?: number | null;
  center_lng?: number | null;
  center_lat?: number | null;
  zoom?: number | null;
  coverage_wkt?: string | null;
  image_url?: string | null;
  remark?: string | null;
  operator?: string | null;
}

export type MapAssetUpdate = Partial<MapAssetCreate>;

// 资源列表（分页/模糊/类型过滤）
export function fetchMapAssets(params: {
  keyword?: string;
  asset_type?: MapAssetType | "";
  page?: number;
  size?: number;
}): Promise<MapAssetPage> {
  return http<MapAssetPage>({ url: "/v1/maps", method: "get", params });
}

// 资源详情
export function fetchMapAsset(id: number): Promise<MapAsset> {
  return http<MapAsset>({ url: `/v1/maps/${id}`, method: "get" });
}

// 创建资源
export function createMapAsset(payload: MapAssetCreate): Promise<MapAsset> {
  return http<MapAsset>({ url: "/v1/maps", method: "post", data: payload });
}

// 更新资源
export function updateMapAsset(
  id: number,
  payload: MapAssetUpdate,
): Promise<MapAsset> {
  return http<MapAsset>({ url: `/v1/maps/${id}`, method: "put", data: payload });
}

// 删除资源
export async function deleteMapAsset(id: number): Promise<void> {
  await http({ url: `/v1/maps/${id}`, method: "delete" });
}

/** 批量删除地图资源 */
export function batchDeleteMapAssets(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/maps/batch-delete", ids);
}
