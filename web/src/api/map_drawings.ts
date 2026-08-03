// 地图手动绘制（标注点/线）API 封装
import { http } from "@/utils/request";

export type MapDrawingKind = "point" | "line";
export type MapDrawingMode = "free" | "coord" | "road";

export interface MapDrawing {
  id: number;
  name: string;
  kind: MapDrawingKind;
  mode: MapDrawingMode;
  project_id: number | null;
  geometry: string;
  points: number[][];
  center_lng: number | null;
  center_lat: number | null;
  length_m: number | null;
  color: string | null;
  remark: string | null;
  operator: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MapDrawingPage {
  total: number;
  items: MapDrawing[];
  page: number;
  size: number;
}

export interface MapDrawingCreate {
  name: string;
  kind: MapDrawingKind;
  mode: MapDrawingMode;
  points: number[][];
  project_id?: number | null;
  color?: string | null;
  remark?: string | null;
  operator?: string | null;
}

export type MapDrawingUpdate = Partial<MapDrawingCreate>;

export interface MapDrawingOptions {
  kinds: { value: MapDrawingKind; label: string }[];
  modes: { value: MapDrawingMode; label: string }[];
  kind_modes: Record<string, MapDrawingMode[]>;
}

// 标注列表（分页/模糊/类型/模式/项目过滤）
export function fetchMapDrawings(params: {
  keyword?: string;
  kind?: MapDrawingKind | "";
  mode?: MapDrawingMode | "";
  project_id?: number | null;
  page?: number;
  size?: number;
}): Promise<MapDrawingPage> {
  return http<MapDrawingPage>({ url: "/v1/map-drawings", method: "get", params });
}

// 可选枚举
export function fetchMapDrawingOptions(): Promise<MapDrawingOptions> {
  return http<MapDrawingOptions>({ url: "/v1/map-drawings/options", method: "get" });
}

// 标注详情
export function fetchMapDrawing(id: number): Promise<MapDrawing> {
  return http<MapDrawing>({ url: `/v1/map-drawings/${id}`, method: "get" });
}

// 创建标注（保存绘制结果）
export function createMapDrawing(payload: MapDrawingCreate): Promise<MapDrawing> {
  return http<MapDrawing>({ url: "/v1/map-drawings", method: "post", data: payload });
}

// 更新标注
export function updateMapDrawing(
  id: number,
  payload: MapDrawingUpdate,
): Promise<MapDrawing> {
  return http<MapDrawing>({
    url: `/v1/map-drawings/${id}`,
    method: "put",
    data: payload,
  });
}

// 删除标注
export async function deleteMapDrawing(id: number): Promise<void> {
  await http({ url: `/v1/map-drawings/${id}`, method: "delete" });
}
