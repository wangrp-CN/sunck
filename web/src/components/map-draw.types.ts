// 地图手动绘制画布共享类型（SFC 的 <script setup> 不能导出，单独抽出）
export type LngLat = [number, number];

/** 已保存标注（渲染到画布的图层） */
export interface SavedDrawing {
  id: number;
  name: string;
  kind: "point" | "line";
  points: number[][];
  color?: string | null;
}

/** 画布交互模式 */
export type DrawMode =
  | "idle"
  | "point-free"
  | "point-coord"
  | "line-free"
  | "line-road";
