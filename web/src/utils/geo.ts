// 坐标系转换：WGS-84（GPS/设备/围栏入库坐标）⇄ GCJ-02（高德地图）。
//
// 与后端 app/core/geo.py 算法保持一致（公开近似实现，与政府标准一致）。
// 设备实时位置后端已直接返回 gcj02 字段，无需前端转换；
// 本工具仅用于「围栏 WKT（WGS-84）」等需要前端上图的场景。

const A = 6378245.0; // 长半轴
const EE = 0.00669342162296594323; // 偏心率平方

function outOfChina(lng: number, lat: number): boolean {
  return !(73.66 < lng && lng < 135.05 && 3.86 < lat && lat < 53.55);
}

function transformLat(lng: number, lat: number): number {
  let ret =
    -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng));
  ret += ((20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(lat * Math.PI) + 40.0 * Math.sin((lat / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret += ((160.0 * Math.sin((lat / 12.0) * Math.PI) + 320.0 * Math.sin((lat * Math.PI) / 30.0)) * 2.0) / 3.0;
  return ret;
}

function transformLng(lng: number, lat: number): number {
  let ret =
    300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng));
  ret += ((20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0) / 3.0;
  ret += ((20.0 * Math.sin(lng * Math.PI) + 40.0 * Math.sin((lng / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret += ((150.0 * Math.sin((lng / 12.0) * Math.PI) + 300.0 * Math.sin((lng / 30.0) * Math.PI)) * 2.0) / 3.0;
  return ret;
}

/** WGS-84 → GCJ-02，返回 [lng, lat]。 */
export function wgs84ToGcj02(lng: number, lat: number): [number, number] {
  if (outOfChina(lng, lat)) return [lng, lat];
  const dLat = transformLat(lng - 105.0, lat - 35.0);
  const dLng = transformLng(lng - 105.0, lat - 35.0);
  const radLat = (lat / 180.0) * Math.PI;
  const magic = Math.sin(radLat);
  const magic2 = 1 - EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic2);
  const dlng = (dLng * 180.0) / ((A / sqrtMagic) * Math.cos(radLat) * Math.PI);
  const dlat = (dLat * 180.0) / (((A * (1 - EE)) / (magic2 * sqrtMagic)) * Math.PI);
  return [lng + dlng, lat + dlat];
}

/**
 * 两点间大圆距离（Haversine），输入 [lng, lat]（度），返回米。
 * GCJ-02 与 WGS-84 的本地偏移对局部距离量算影响可忽略，直接用于地图测距。
 */
export function haversineMeters(a: [number, number], b: [number, number]): number {
  const R = 6371000; // 地球平均半径（米）
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b[1] - a[1]);
  const dLng = rad(b[0] - a[0]);
  const lat1 = rad(a[1]);
  const lat2 = rad(b[1]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** 距离格式化：<1000m 显示米，否则显示千米。 */
export function fmtDistance(m: number): string {
  return m < 1000 ? `${m.toFixed(1)} m` : `${(m / 1000).toFixed(2)} km`;
}

/**
 * 解析 WKT 多边形/线（WGS-84）为 GCJ-02 坐标路径 [[lng,lat], ...]。
 * 支持 POLYGON((...)) / LINESTRING(...) 的首个环。
 */
export function parseWktToGcjPath(wkt: string | null | undefined): [number, number][] {
  if (!wkt) return [];
  const m = wkt.match(/\(([^()]*)\)/);
  if (!m) return [];
  const parts = m[1].trim().split(/[\s,]+/).filter(Boolean);
  const out: [number, number][] = [];
  for (let i = 0; i + 1 < parts.length; i += 2) {
    const lng = parseFloat(parts[i]);
    const lat = parseFloat(parts[i + 1]);
    if (Number.isNaN(lng) || Number.isNaN(lat)) continue;
    out.push(wgs84ToGcj02(lng, lat));
  }
  return out;
}

/**
 * GCJ-02 → WGS-84，返回 [lng, lat]。与 wgs84ToGcj02 互逆（迭代精化）。
 * 用于：地图上绘制的围栏（GCJ-02 坐标）落库前转换回 WGS-84。
 */
export function gcj02ToWgs84(lng: number, lat: number): [number, number] {
  if (outOfChina(lng, lat)) return [lng, lat];
  let wgsLng = lng;
  let wgsLat = lat;
  // 牛顿式迭代：用正向变换反推原始 WGS 坐标，3 次即收敛到厘米级
  for (let i = 0; i < 3; i++) {
    const [gl, gt] = wgs84ToGcj02(wgsLng, wgsLat);
    wgsLng += lng - gl;
    wgsLat += lat - gt;
  }
  return [wgsLng, wgsLat];
}

/**
 * 由多边形顶点（GCJ-02 或 WGS-84 的 [lng,lat] 序列）生成闭合 WKT 字符串。
 * 自动闭合首尾（WKT POLYGON 要求首末点相同），用于围栏绘制回填空。
 * 顶点不足 3 个时返回 null（无法构成面）。
 */
export function pointsToWkt(points: [number, number][]): string | null {
  if (!points || points.length < 3) return null;
  const ring = points
    .map((p) => {
      const lng = Number(p[0]).toFixed(6);
      const lat = Number(p[1]).toFixed(6);
      return `${lng} ${lat}`;
    })
    .join(", ");
  // 闭合：首点重复在末尾
  const first = `${Number(points[0][0]).toFixed(6)} ${Number(points[0][1]).toFixed(6)}`;
  return `POLYGON((${ring}, ${first}))`;
}
