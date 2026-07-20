<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Location } from "@element-plus/icons-vue";
import { isAmapEnabled, loadAMap } from "@/utils/amap";
import { fmtDistance, haversineMeters, parseWktToGcjPath } from "@/utils/geo";
import type { MapDevice, MapFence } from "@/types";

const props = withDefaults(
  defineProps<{
    devices?: MapDevice[];
    fences?: MapFence[];
    center?: [number, number];
    zoom?: number;
    height?: string;
  }>(),
  {
    devices: () => [],
    fences: () => [],
    center: () => [116.397, 39.908] as [number, number],
    zoom: 14,
    height: "320px",
  },
);

const emit = defineEmits<{
  (e: "ready"): void;
  (e: "fence-click", payload: { id: number; name: string }): void;
  // 围栏绘制完成：返回 GCJ-02 顶点序列（至少 3 点），由父组件转换为 WGS-84 WKT 落库
  (e: "fence-draw", payload: { points: [number, number][] }): void;
}>();

const container = ref<HTMLDivElement | null>(null);
const enabled = isAmapEnabled();
const ready = ref(false);
const error = ref("");

// ============ 测距（真图 / 模拟图共用）============
const measuring = ref(false); // 是否处于测距模式
const measurePts = ref<[number, number][]>([]); // 已取的点（GCJ-02 [lng,lat]）

// 累计距离（米）
const measureTotal = computed(() => {
  let sum = 0;
  const p = measurePts.value;
  for (let i = 1; i < p.length; i++) sum += haversineMeters(p[i - 1], p[i]);
  return sum;
});
const measureTotalText = computed(() => fmtDistance(measureTotal.value));

function toggleMeasure() {
  measuring.value = !measuring.value;
  if (!measuring.value) clearMeasure();
}
function clearMeasure() {
  measurePts.value = [];
  if (map) redrawRealMeasure();
}
function undoMeasure() {
  measurePts.value = measurePts.value.slice(0, -1);
  if (map) redrawRealMeasure();
}

// ============ 围栏绘制（真图 / 模拟图共用）============
// 与测距互斥：进入绘制模式会自动退出测距。点击地图取多边形顶点，完成 emit 回传。
const drawing = ref(false); // 是否处于绘制模式
const drawPts = ref<[number, number][]>([]); // 已取顶点（GCJ-02 [lng,lat]）
let drawOverlays: any[] = []; // 真图绘制草稿覆盖物

// 真图绘制草稿（多边形 + 顶点）
function redrawRealDraft() {
  if (!map || !AMap) return;
  for (const o of drawOverlays) map.remove(o);
  drawOverlays = [];
  const pts = drawPts.value;
  if (pts.length < 2) return;
  const poly = new AMap.Polygon({
    path: pts,
    strokeColor: "#1677ff",
    strokeWeight: 2,
    strokeOpacity: 0.9,
    fillColor: "#1677ff",
    fillOpacity: 0.12,
    bubble: true,
  });
  map.add(poly);
  drawOverlays.push(poly);
  for (const p of pts) {
    const dot = new AMap.CircleMarker({
      center: p,
      radius: 4,
      fillColor: "#1677ff",
      fillOpacity: 1,
      strokeColor: "#fff",
      strokeWeight: 2,
      zIndex: 210,
    });
    map.add(dot);
    drawOverlays.push(dot);
  }
}

function toggleDraw() {
  drawing.value = !drawing.value;
  if (drawing.value) {
    measuring.value = false;
    clearMeasure();
    drawPts.value = [];
    if (map) redrawRealDraft();
  } else {
    clearDraw();
  }
}
function clearDraw() {
  drawPts.value = [];
  if (map) redrawRealDraft();
}
function undoDraw() {
  drawPts.value = drawPts.value.slice(0, -1);
  if (map) redrawRealDraft();
}
function finishDraw() {
  if (drawPts.value.length >= 3) {
    emit("fence-draw", { points: drawPts.value.map((p) => [p[0], p[1]] as [number, number]) });
  }
  drawing.value = false;
  clearDraw();
}

// ============ 高德真实地图（配置了 Key 时）============
let AMap: any = null;
let map: any = null;
const markerMap = new Map<string, any>();
let fenceOverlays: any[] = [];
let trajOverlays: any[] = [];
let movingMarker: any = null;
let measureOverlays: any[] = []; // 真图测距的折线/点/文本
let fitted = false;

const TYPE_COLOR: Record<string, string> = {
  locate: "#2f54eb",
  anti_intrusion: "#fa8c16",
  train_approach: "#cf1322",
};

function deviceContent(d: MapDevice): string {
  const color = d.live ? "#52c41a" : TYPE_COLOR[d.device_type] || "#888";
  return `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.35);"></div>`;
}

function renderDevices() {
  if (!map) return;
  for (const m of markerMap.values()) map.remove(m);
  markerMap.clear();
  for (const d of props.devices) {
    if (!d.lng || !d.lat) continue;
    const marker = new AMap.Marker({
      position: [d.lng, d.lat],
      anchor: "center",
      content: deviceContent(d),
      title: `${d.name}（${d.device_no}）`,
      label: {
        content: d.name,
        direction: "top",
        offset: new AMap.Pixel(0, -8),
      },
    });
    map.add(marker);
    markerMap.set(d.device_no, marker);
  }
  fitIfNeeded();
}

function renderFences() {
  if (!map) return;
  for (const o of fenceOverlays) map.remove(o);
  fenceOverlays = [];
  for (const f of props.fences) {
    if (!f.geometry_wkt) continue;
    const path = parseWktToGcjPath(f.geometry_wkt);
    if (path.length < 3) continue;
    const poly = new AMap.Polygon({
      path,
      strokeColor: "#ff6a00",
      strokeWeight: 2,
      strokeOpacity: 0.9,
      fillColor: "#ffb74d",
      fillOpacity: 0.15,
      bubble: true,
      cursor: "pointer",
    });
    // 围栏点击 → 关联作业计划弹层（测距/绘制模式下让给取点，不触发）
    poly.on("click", () => {
      if (measuring.value || drawing.value) return;
      emit("fence-click", { id: f.id, name: f.name });
    });
    map.add(poly);
    fenceOverlays.push(poly);
  }
}

function fitIfNeeded() {
  const pts = props.devices.filter((d) => d.lng && d.lat).map((d) => [d.lng, d.lat]);
  if (pts.length === 0) return;
  if (!fitted) {
    map.setFitView(undefined, false, [40, 40, 40, 40]);
    fitted = true;
  }
}

async function initAmap() {
  try {
    AMap = await loadAMap();
  } catch (e: any) {
    error.value = e?.message === "AMAP_KEY_NOT_SET" ? "" : e?.message || "高德地图加载失败";
    return;
  }
  map = new AMap.Map(container.value, {
    zoom: props.zoom,
    center: props.center,
    viewMode: "2D",
    mapStyle: "amap://styles/whitesmoke",
    resizeEnable: true,
  });
  renderDevices();
  renderFences();
  map.on("click", onRealMapClick);
  ready.value = true;
  emit("ready");
}

// ---- 真图：测距 / 绘制 共用点击 ----
function onRealMapClick(e: any) {
  if (measuring.value && e?.lnglat) {
    measurePts.value = [...measurePts.value, [e.lnglat.getLng(), e.lnglat.getLat()]];
    redrawRealMeasure();
    return;
  }
  if (drawing.value && e?.lnglat) {
    drawPts.value = [...drawPts.value, [e.lnglat.getLng(), e.lnglat.getLat()]];
    redrawRealDraft();
  }
}

function redrawRealMeasure() {
  if (!map || !AMap) return;
  for (const o of measureOverlays) map.remove(o);
  measureOverlays = [];
  const pts = measurePts.value;
  if (pts.length === 0) return;
  // 折线
  if (pts.length > 1) {
    const line = new AMap.Polyline({
      path: pts,
      strokeColor: "#722ed1",
      strokeWeight: 4,
      strokeStyle: "dashed",
      strokeOpacity: 0.9,
      lineJoin: "round",
    });
    map.add(line);
    measureOverlays.push(line);
  }
  // 顶点 + 分段/累计距离文本
  let acc = 0;
  for (let i = 0; i < pts.length; i++) {
    const dot = new AMap.CircleMarker({
      center: pts[i],
      radius: 4,
      fillColor: "#722ed1",
      fillOpacity: 1,
      strokeColor: "#fff",
      strokeWeight: 2,
      zIndex: 210,
    });
    map.add(dot);
    measureOverlays.push(dot);
    if (i > 0) acc += haversineMeters(pts[i - 1], pts[i]);
    const label =
      i === 0
        ? "起点"
        : i === pts.length - 1
          ? `合计 ${fmtDistance(acc)}`
          : fmtDistance(acc);
    const txt = new AMap.Text({
      text: label,
      position: pts[i],
      anchor: "bottom-center",
      offset: new AMap.Pixel(0, -8),
      style: {
        background: "#722ed1",
        color: "#fff",
        border: "none",
        "border-radius": "3px",
        padding: "1px 6px",
        "font-size": "12px",
      },
      zIndex: 211,
    });
    map.add(txt);
    measureOverlays.push(txt);
  }
}

// ---- 真图设备聚焦（告警联动）----
function focusRealDevice(deviceNo: string) {
  const marker = markerMap.get(deviceNo);
  if (!marker || !map) return;
  map.setCenter(marker.getPosition());
  if (map.getZoom() < 16) map.setZoom(16);
  if (marker.setAnimation) {
    marker.setAnimation("AMAP_ANIMATION_BOUNCE");
    setTimeout(() => marker.setAnimation && marker.setAnimation("AMAP_ANIMATION_NONE"), 2400);
  }
}

// ============ 模拟地图（未配置 Key / 加载失败时）============
// 把 GCJ-02 坐标投影到画布，绘制网格、围栏、设备、轨迹。无需联网或 Key。
const VB_W = 1000;
const VB_H = 600;
const PAD = { l: 52, r: 24, t: 24, b: 40 };

// 轨迹点（由 setTrajectory 注入，GCJ-02）
const trajPoints = ref<[number, number][]>([]);
const movingPos = ref<[number, number] | null>(null);
// 告警联动高亮的设备编号（模拟图）
const highlightNo = ref<string | null>(null);
const mockSvg = ref<SVGSVGElement | null>(null);

// 每个实例唯一的 defs id（避免同页多个 MapPanel 时 url(#id) 互相串扰）
const uid = `m${Math.random().toString(36).slice(2, 9)}`;
const ids = {
  bg: `bgGrad-${uid}`,
  traj: `trajGrad-${uid}`,
  fence: `fenceFill-${uid}`,
  fenceGlow: `fenceGlow-${uid}`,
  softGlow: `softGlow-${uid}`,
  arrow: `arrow-${uid}`,
};
const url = {
  bg: `url(#${ids.bg})`,
  traj: `url(#${ids.traj})`,
  fence: `url(#${ids.fence})`,
  fenceGlow: `url(#${ids.fenceGlow})`,
  softGlow: `url(#${ids.softGlow})`,
  arrow: `url(#${ids.arrow})`,
};

const allPoints = computed<[number, number][]>(() => {
  const pts: [number, number][] = [];
  for (const d of props.devices) if (d.lng && d.lat) pts.push([d.lng, d.lat]);
  for (const f of props.fences) for (const p of parseWktToGcjPath(f.geometry_wkt)) pts.push(p);
  for (const p of trajPoints.value) pts.push(p);
  return pts;
});

const bounds = computed(() => {
  const pts = allPoints.value;
  if (pts.length === 0) {
    const c = props.center;
    return { minLng: c[0] - 0.02, maxLng: c[0] + 0.02, minLat: c[1] - 0.01, maxLat: c[1] + 0.01 };
  }
  let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const [lng, lat] of pts) {
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  const padLng = Math.max(0.002, (maxLng - minLng) * 0.15);
  const padLat = Math.max(0.001, (maxLat - minLat) * 0.15);
  return {
    minLng: minLng - padLng,
    maxLng: maxLng + padLng,
    minLat: minLat - padLat,
    maxLat: maxLat + padLat,
  };
});

function project(lng: number, lat: number): { x: number; y: number } {
  const b = bounds.value;
  const x = PAD.l + ((lng - b.minLng) / (b.maxLng - b.minLng)) * (VB_W - PAD.l - PAD.r);
  const y = PAD.t + (1 - (lat - b.minLat) / (b.maxLat - b.minLat)) * (VB_H - PAD.t - PAD.b);
  return { x, y };
}

// 反投影：viewBox 坐标(x,y) → GCJ-02 [lng,lat]
function unproject(x: number, y: number): [number, number] {
  const b = bounds.value;
  const lng = b.minLng + ((x - PAD.l) / (VB_W - PAD.l - PAD.r)) * (b.maxLng - b.minLng);
  const lat = b.minLat + (1 - (y - PAD.t) / (VB_H - PAD.t - PAD.b)) * (b.maxLat - b.minLat);
  return [lng, lat];
}

// 模拟图点击：测距 / 绘制 模式下取点（屏幕坐标换算到 viewBox 再反投影）
function onMockClick(evt: MouseEvent) {
  if ((!measuring.value && !drawing.value) || !mockSvg.value) return;
  const svg = mockSvg.value;
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX;
  pt.y = evt.clientY;
  const ctm = svg.getScreenCTM();
  if (!ctm) return;
  const loc = pt.matrixTransform(ctm.inverse());
  if (measuring.value) {
    measurePts.value = [...measurePts.value, unproject(loc.x, loc.y)];
  } else if (drawing.value) {
    drawPts.value = [...drawPts.value, unproject(loc.x, loc.y)];
  }
}

// 模拟图测距：投影点 + 折线 + 分段/累计标签
const measureProjected = computed(() => measurePts.value.map((p) => project(p[0], p[1])));
const measurePolyline = computed(() =>
  measureProjected.value.map((p) => `${p.x},${p.y}`).join(" "),
);

// 绘制草稿（多边形 + 顶点）
const drawProjected = computed(() => drawPts.value.map((p) => project(p[0], p[1])));
const drawPolyline = computed(() =>
  drawProjected.value.map((p) => `${p.x},${p.y}`).join(" "),
);
const measureLabels = computed(() => {
  const pr = measureProjected.value;
  const pts = measurePts.value;
  const out: { x: number; y: number; text: string }[] = [];
  let acc = 0;
  for (let i = 0; i < pr.length; i++) {
    if (i > 0) acc += haversineMeters(pts[i - 1], pts[i]);
    out.push({
      x: pr[i].x,
      y: pr[i].y - 10,
      text: i === 0 ? "起点" : i === pr.length - 1 ? `合计 ${fmtDistance(acc)}` : fmtDistance(acc),
    });
  }
  return out;
});

const fencePaths = computed(() =>
  props.fences
    .map((f) => ({
      id: f.id,
      name: f.name,
      pts: parseWktToGcjPath(f.geometry_wkt).map(([lng, lat]) => project(lng, lat)),
    }))
    .filter((f) => f.pts.length >= 3),
);

// 围栏点击（模拟模式）：非测距/非绘制模式下触发关联作业计划弹层
function onFenceMockClick(id: number, name: string) {
  if (measuring.value || drawing.value) return; // 让取点获得该点（事件继续冒泡到 svg 取点）
  emit("fence-click", { id, name });
}

const deviceMarks = computed(() =>
  props.devices.map((d) => ({
    ...d,
    pr: d.lng && d.lat ? project(d.lng, d.lat) : null,
    color: d.live ? "#52c41a" : TYPE_COLOR[d.device_type] || "#888",
  })),
);

// 高亮设备（告警联动）投影位置
const highlightProj = computed(() => {
  if (!highlightNo.value) return null;
  const d = props.devices.find((x) => x.device_no === highlightNo.value);
  if (!d || !d.lng || !d.lat) return null;
  return project(d.lng, d.lat);
});

const trajProjected = computed(() => trajPoints.value.map((p) => project(p[0], p[1])));
const trajPolyline = computed(() => trajProjected.value.map((p) => `${p.x},${p.y}`).join(" "));
const movingProj = computed(() => (movingPos.value ? project(movingPos.value[0], movingPos.value[1]) : null));

// 经纬度刻度（每轴约 4 格）
const lngTicks = computed(() => {
  const b = bounds.value;
  const n = 4;
  const out: { x: number; label: string }[] = [];
  for (let i = 1; i < n; i++) {
    const lng = b.minLng + ((b.maxLng - b.minLng) * i) / n;
    const x = PAD.l + ((VB_W - PAD.l - PAD.r) * i) / n;
    out.push({ x, label: lng.toFixed(4) });
  }
  return out;
});
const latTicks = computed(() => {
  const b = bounds.value;
  const n = 4;
  const out: { y: number; label: string }[] = [];
  for (let i = 1; i < n; i++) {
    const lat = b.minLat + ((b.maxLat - b.minLat) * i) / n;
    const y = PAD.t + ((VB_H - PAD.t - PAD.b) * (n - i)) / n;
    out.push({ y, label: lat.toFixed(4) });
  }
  return out;
});

// 模拟图细网格（无标签，纯视觉密度）
const gridV = computed(() => {
  const n = 16;
  const out: number[] = [];
  for (let i = 0; i <= n; i++) out.push(PAD.l + ((VB_W - PAD.l - PAD.r) * i) / n);
  return out;
});
const gridH = computed(() => {
  const n = 16;
  const out: number[] = [];
  for (let i = 0; i <= n; i++) out.push(PAD.t + ((VB_H - PAD.t - PAD.b) * i) / n);
  return out;
});

// 比例尺：按中心纬度估算每像素米数，取最接近 ~120px 的整刻度
const scaleBar = computed(() => {
  const b = bounds.value;
  const plotW = VB_W - PAD.l - PAD.r;
  const x0 = PAD.l + 14;
  const y0 = VB_H - PAD.b - 10;
  if (plotW <= 0 || b.maxLng <= b.minLng) return { px: 100, label: "100 m", x: x0, y: y0 };
  const centerLat = (b.minLat + b.maxLat) / 2;
  const metersPerPx = ((b.maxLng - b.minLng) / plotW) * 111320 * Math.cos((centerLat * Math.PI) / 180);
  const raw = metersPerPx * 120;
  const steps = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000];
  let nice = steps[steps.length - 1];
  for (const s of steps) {
    if (s >= raw) {
      nice = s;
      break;
    }
  }
  return { px: nice / metersPerPx, label: nice >= 1000 ? `${nice / 1000} km` : `${nice} m`, x: x0, y: y0 };
});

// 移动标记拖尾：轨迹最近若干点（渐隐高亮）
const trailProjected = computed(() => {
  const all = trajProjected.value;
  return all.length > 1 ? all.slice(Math.max(0, all.length - 12)) : [];
});
const trailPolyline = computed(() => trailProjected.value.map((p) => `${p.x},${p.y}`).join(" "));

// ============ 模拟地图「真图质感」底图（路网/地形/铁路）============
// 纯装饰层：在 viewBox 坐标系内程序化生成稳定的路网与地形，不依赖真实瓦片/Key。
// 固定种子保证画面稳定；pointer-events:none 保证测距点击穿透；不影响围栏/设备交互。
function mulberry32(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const PL = PAD.l;
const PR = VB_W - PAD.r;
const PT = PAD.t;
const PB = VB_H - PAD.b;
const PW = PR - PL;
const PH = PB - PT;
function clamp(v: number, lo: number, hi: number) {
  return v < lo ? lo : v > hi ? hi : v;
}
function ptsStr(pts: { x: number; y: number }[]): string {
  return pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}
function blobPts(
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  n: number,
  rng: () => number,
) {
  const pts: { x: number; y: number }[] = [];
  for (let i = 0; i < n; i++) {
    const a = (Math.PI * 2 * i) / n;
    const k = 0.78 + rng() * 0.44;
    pts.push({ x: cx + Math.cos(a) * rx * k, y: cy + Math.sin(a) * ry * k });
  }
  return pts;
}

interface RoadSeg {
  pts: { x: number; y: number }[];
  kind: "highway" | "arterial" | "minor";
}
const baseRoads: RoadSeg[] = (() => {
  const r = mulberry32(20260716);
  const roads: RoadSeg[] = [];
  // 横向主干/支路
  const nh = 4 + Math.floor(r() * 2);
  for (let i = 0; i < nh; i++) {
    const y0 = PT + PH * ((i + 0.5) / nh) + (r() - 0.5) * PH * 0.07;
    const segs = 6;
    const pts: { x: number; y: number }[] = [];
    for (let s = 0; s <= segs; s++) {
      const x = PL + (PW * s) / segs;
      const y = y0 + (r() - 0.5) * PH * 0.03;
      pts.push({ x, y: clamp(y, PT + 4, PB - 4) });
    }
    roads.push({ pts, kind: i % 2 === 0 ? "arterial" : "minor" });
  }
  // 纵向主干/支路
  const nv = 5 + Math.floor(r() * 2);
  for (let i = 0; i < nv; i++) {
    const x0 = PL + PW * ((i + 0.5) / nv) + (r() - 0.5) * PW * 0.06;
    const segs = 5;
    const pts: { x: number; y: number }[] = [];
    for (let s = 0; s <= segs; s++) {
      const y = PT + (PH * s) / segs;
      const x = x0 + (r() - 0.5) * PW * 0.03;
      pts.push({ x: clamp(x, PL + 4, PR - 4), y });
    }
    roads.push({ pts, kind: i % 2 === 1 ? "arterial" : "minor" });
  }
  // 斜向高速公路（带弧度）
  const hpts: { x: number; y: number }[] = [];
  const hs = 12;
  for (let s = 0; s <= hs; s++) {
    const f = s / hs;
    const x = PL + PW * f + Math.sin(f * Math.PI) * PW * 0.14;
    const y = PT + PH * f - Math.sin(f * Math.PI) * PH * 0.12;
    hpts.push({ x: clamp(x, PL + 2, PR - 2), y: clamp(y, PT + 2, PB - 2) });
  }
  roads.push({ pts: hpts, kind: "highway" });
  return roads;
})();

const baseRiver: { x: number; y: number }[] = (() => {
  const segs = 16;
  const pts: { x: number; y: number }[] = [];
  for (let s = 0; s <= segs; s++) {
    const f = s / segs;
    const x = PL + PW * (0.08 + 0.82 * f) + Math.sin(f * Math.PI * 1.3) * PW * 0.05;
    const y = PT + PH * (0.86 - 0.72 * f) + Math.cos(f * Math.PI) * PH * 0.04;
    pts.push({ x: clamp(x, PL + 6, PR - 6), y: clamp(y, PT + 6, PB - 6) });
  }
  return pts;
})();

const baseLake: { x: number; y: number }[] = blobPts(
  PL + PW * 0.8,
  PT + PH * 0.18,
  PW * 0.09,
  PH * 0.06,
  11,
  mulberry32(404),
);
const baseParks: { x: number; y: number }[][] = [
  blobPts(PL + PW * 0.2, PT + PH * 0.72, PW * 0.12, PH * 0.09, 12, mulberry32(31)),
  blobPts(PL + PW * 0.6, PT + PH * 0.8, PW * 0.1, PH * 0.07, 11, mulberry32(57)),
];
const baseContours: { x: number; y: number }[][] = (() => {
  const ccx = PL + PW * 0.52;
  const ccy = PT + PH * 0.14;
  const out: { x: number; y: number }[][] = [];
  for (let k = 1; k <= 4; k++) {
    const rx = PW * 0.05 * k;
    const ry = PH * 0.04 * k;
    const seg = 24;
    const pts: { x: number; y: number }[] = [];
    for (let s = 0; s <= seg; s++) {
      const a = (Math.PI * 2 * s) / seg;
      pts.push({ x: ccx + Math.cos(a) * rx, y: ccy + Math.sin(a) * ry * 0.75 });
    }
    out.push(pts);
  }
  return out;
})();

// 铁路走廊（涉铁主题）：底线 + 枕木虚线
const baseRailway: { x: number; y: number }[] = (() => {
  const segs = 10;
  const pts: { x: number; y: number }[] = [];
  for (let s = 0; s <= segs; s++) {
    const f = s / segs;
    const x = PL + PW * (0.12 + 0.78 * f) + Math.sin(f * Math.PI * 0.8) * PW * 0.04;
    const y = PT + PH * (0.2 + 0.62 * f) + Math.cos(f * Math.PI) * PH * 0.05;
    pts.push({ x: clamp(x, PL + 6, PR - 6), y: clamp(y, PT + 6, PB - 6) });
  }
  return pts;
})();

// ---- 对外暴露（与高德模式一致；按 map 是否存在分流）----
function setTrajectory(path: [number, number][]) {
  if (map) {
    clearTrajectory();
    if (path.length === 0) return;
    const line = new AMap.Polyline({
      path,
      strokeColor: "#1677ff",
      strokeWeight: 5,
      strokeOpacity: 0.9,
      showDir: true,
      lineJoin: "round",
      lineCap: "round",
    });
    map.add(line);
    trajOverlays.push(line);
    map.setFitView(undefined, false, [40, 40, 40, 40]);
  } else {
    trajPoints.value = path;
  }
}
function clearTrajectory() {
  if (map) {
    for (const o of trajOverlays) map.remove(o);
    trajOverlays = [];
  } else {
    trajPoints.value = [];
  }
}
function setMovingMarker(pos: [number, number]) {
  if (map) {
    if (!movingMarker) {
      movingMarker = new AMap.Marker({
        position: pos,
        anchor: "center",
        content:
          '<div style="width:18px;height:18px;border-radius:50%;background:#1677ff;border:3px solid #fff;box-shadow:0 0 6px rgba(22,119,255,.8);"></div>',
        zIndex: 200,
      });
      map.add(movingMarker);
    } else {
      movingMarker.setPosition(pos);
    }
  } else {
    movingPos.value = pos;
  }
}
function removeMovingMarker() {
  if (map && movingMarker) {
    map.remove(movingMarker);
    movingMarker = null;
  } else {
    movingPos.value = null;
  }
}
function fitView() {
  if (map) map.setFitView(undefined, false, [40, 40, 40, 40]);
  // 模拟模式：bounds 由响应式数据自动重算，无需额外操作
}

// 聚焦某设备（告警↔地图联动）。真图定位弹跳；模拟图脉冲高亮。
let highlightTimer: number | undefined;
function focusDevice(deviceNo: string | null) {
  if (!deviceNo) return;
  if (map) {
    focusRealDevice(deviceNo);
  } else {
    highlightNo.value = deviceNo;
    if (highlightTimer) window.clearTimeout(highlightTimer);
    highlightTimer = window.setTimeout(() => (highlightNo.value = null), 3000);
  }
}

function initMock() {
  ready.value = true;
  emit("ready");
}

// 真图：devices/fences 异步刷新时重渲染，保证 focusDevice 能命中 marker
watch(
  () => props.devices,
  () => {
    if (map) renderDevices();
  },
  { deep: true },
);
watch(
  () => props.fences,
  () => {
    if (map) renderFences();
  },
  { deep: true },
);

onMounted(() => {
  if (enabled) initAmap();
  else initMock();
});

onBeforeUnmount(() => {
  if (map) {
    map.destroy();
    map = null;
  }
});

defineExpose({
  setTrajectory,
  clearTrajectory,
  setMovingMarker,
  removeMovingMarker,
  fitView,
  focusDevice,
  clearDraft: () => {
    drawing.value = false;
    clearDraw();
  },
  isDrawing: () => drawing.value,
  isReady: () => ready.value,
});
</script>

<template>
  <div class="map-panel">
    <!-- 工具条（测距 / 围栏绘制，真图 / 模拟图通用） -->
    <div class="map-tools">
      <template v-if="!measuring && !drawing">
        <button class="tool-btn" type="button" @click="toggleMeasure">测距</button>
        <button class="tool-btn" type="button" @click="toggleDraw">绘制围栏</button>
      </template>
      <template v-else-if="measuring">
        <button class="tool-btn active" type="button" @click="toggleMeasure">结束测距</button>
        <button class="tool-btn" type="button" :disabled="!measurePts.length" @click="undoMeasure">
          撤销
        </button>
        <button class="tool-btn" type="button" :disabled="!measurePts.length" @click="clearMeasure">
          清空
        </button>
        <span class="tool-total">
          {{ measurePts.length > 1 ? measureTotalText : "点击地图取点" }}
        </span>
      </template>
      <template v-else>
        <button class="tool-btn active" type="button" @click="toggleDraw">结束绘制</button>
        <button class="tool-btn" type="button" :disabled="drawPts.length < 2" @click="undoDraw">
          撤销
        </button>
        <button class="tool-btn" type="button" :disabled="!drawPts.length" @click="clearDraw">
          清空
        </button>
        <button
          class="tool-btn primary"
          type="button"
          :disabled="drawPts.length < 3"
          @click="finishDraw"
        >
          完成
        </button>
        <span class="tool-total">
          {{ drawPts.length }} 点{{ drawPts.length < 3 ? "（至少 3 点）" : "" }}
        </span>
      </template>
    </div>

    <!-- 围栏可点击提示 / 绘制提示 -->
    <div v-if="drawing" class="fence-hint draw-hint">
      <el-icon><Location /></el-icon> 点击地图逐点绘制围栏，至少 3 点后点「完成」
    </div>
    <div v-else-if="!measuring && props.fences.length" class="fence-hint">
      <el-icon><Location /></el-icon> 点击围栏查看关联作业计划
    </div>

    <!-- 真实高德地图 -->
    <div v-if="enabled && !error" ref="container" class="map-canvas" :style="{ height }"></div>

    <!-- 模拟地图（降级）：SVG 投影渲染围栏/设备/轨迹，无需 Key -->
    <div v-else class="map-mock" :style="{ height }">
      <div class="mock-badge">
        <el-icon><Location /></el-icon>
        模拟地图（未配置高德 Key，坐标系 GCJ-02）
      </div>
      <svg
        ref="mockSvg"
        :viewBox="`0 0 ${VB_W} ${VB_H}`"
        class="mock-svg"
        :class="{ measuring, drawing }"
        preserveAspectRatio="xMidYMid meet"
        @click="onMockClick"
      >
        <defs>
          <linearGradient :id="ids.bg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#f4f8ff" />
            <stop offset="100%" stop-color="#e9f1fb" />
          </linearGradient>
          <linearGradient :id="ids.traj" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#69b1ff" />
            <stop offset="100%" stop-color="#0958d9" />
          </linearGradient>
          <radialGradient :id="ids.fence" cx="50%" cy="50%" r="75%">
            <stop offset="0%" stop-color="#ffd8a8" stop-opacity="0.32" />
            <stop offset="100%" stop-color="#ffa94d" stop-opacity="0.10" />
          </radialGradient>
          <filter :id="ids.fenceGlow" x="-25%" y="-25%" width="150%" height="150%">
            <feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="#ff8c1a" flood-opacity="0.45" />
          </filter>
          <filter :id="ids.softGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="2.4" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <marker :id="ids.arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#0958d9" />
          </marker>
        </defs>

        <!-- 背景 -->
        <rect :x="PAD.l" :y="PAD.t" :width="VB_W - PAD.l - PAD.r" :height="VB_H - PAD.t - PAD.b"
          :fill="url.bg" stroke="#cdd7e6" stroke-width="1" />

        <!-- 真图质感底图：地形（水域/绿地/等高线）+ 铁路 + 路网 -->
        <g class="base-layer" pointer-events="none">
          <!-- 绿地 -->
          <polygon v-for="(p, i) in baseParks" :key="'park' + i" :points="ptsStr(p)" class="park-fill" />
          <!-- 湖泊 -->
          <polygon :points="ptsStr(baseLake)" class="lake-fill" />
          <!-- 河流（岸线 + 主流） -->
          <polyline :points="ptsStr(baseRiver)" fill="none" class="river-bank" />
          <polyline :points="ptsStr(baseRiver)" fill="none" class="river-core" />
          <!-- 等高线（地形起伏） -->
          <polyline v-for="(c, i) in baseContours" :key="'ct' + i" :points="ptsStr(c)"
            fill="none" class="contour-line" />
          <!-- 铁路走廊（涉铁主题：底线 + 枕木虚线） -->
          <polyline :points="ptsStr(baseRailway)" fill="none" class="rail-casing" />
          <polyline :points="ptsStr(baseRailway)" fill="none" class="rail-core" />
          <polyline :points="ptsStr(baseRailway)" fill="none" class="rail-ties" />
          <!-- 路网（高速/主干/支路，含描边 casing） -->
          <template v-for="(rd, i) in baseRoads" :key="'rd' + i">
            <polyline :points="ptsStr(rd.pts)" fill="none" :class="['road-casing', 'road-' + rd.kind]" />
            <polyline :points="ptsStr(rd.pts)" fill="none" :class="['road-core', 'road-' + rd.kind]" />
          </template>
        </g>

        <!-- 细网格（无标签，纯密度，弱化以突出路网） -->
        <g stroke="#eef4fb" stroke-width="1" shape-rendering="crispEdges">
          <line v-for="(x, i) in gridV" :key="'gv' + i" :x1="x" :y1="PAD.t" :x2="x" :y2="VB_H - PAD.b" />
          <line v-for="(y, i) in gridH" :key="'gh' + i" :x1="PAD.l" :y1="y" :x2="VB_W - PAD.r" :y2="y" />
        </g>
        <!-- 主网格（刻度位，略深） -->
        <g stroke="#d3dcec" stroke-width="1.1" shape-rendering="crispEdges">
          <line v-for="t in lngTicks" :key="'gv2' + t.x" :x1="t.x" :y1="PAD.t" :x2="t.x" :y2="VB_H - PAD.b" />
          <line v-for="t in latTicks" :key="'gh2' + t.y" :x1="PAD.l" :y1="t.y" :x2="VB_W - PAD.r" :y2="t.y" />
        </g>

        <!-- 围栏多边形（可点击 → 关联作业计划） -->
        <g
          v-for="f in fencePaths"
          :key="f.id"
          class="fence-g"
          :class="{ measuring }"
          @click="onFenceMockClick(f.id, f.name)"
        >
          <title>{{ f.name }}（点击查看关联作业计划）</title>
          <polygon
            :points="f.pts.map((p) => p.x + ',' + p.y).join(' ')"
            :fill="url.fence" stroke="#ff6a00" stroke-width="2" stroke-opacity="0.9"
            :filter="url.fenceGlow" class="fence-poly"
          />
          <!-- 监控中呼吸虚线边框 -->
          <polygon
            :points="f.pts.map((p) => p.x + ',' + p.y).join(' ')"
            fill="none" stroke="#ff8c1a" stroke-width="1.6" stroke-opacity="0.9"
            stroke-dasharray="7 5" class="fence-dash"
          />
          <text :x="f.pts[0].x + 6" :y="f.pts[0].y - 6" font-size="11" fill="#fff" font-weight="600"
            paint-order="stroke" stroke="#ff6a00" stroke-width="6" stroke-linejoin="round">
            {{ f.name }}
          </text>
        </g>

        <!-- 围栏绘制草稿（多边形 + 顶点） -->
        <g v-if="drawing && drawProjected.length" class="draw-g">
          <polygon
            v-if="drawProjected.length >= 2"
            :points="drawPolyline"
            fill="#1677ff" fill-opacity="0.12" stroke="#1677ff" stroke-width="2"
          />
          <circle
            v-for="(p, i) in drawProjected"
            :key="'dp' + i"
            :cx="p.x" :cy="p.y" r="4" fill="#1677ff" stroke="#fff" stroke-width="1.5"
          />
          <text
            v-if="drawProjected.length"
            :x="drawProjected[0].x + 6" :y="drawProjected[0].y - 6"
            font-size="11" fill="#1677ff" font-weight="600"
            paint-order="stroke" stroke="#fff" stroke-width="3" stroke-linejoin="round"
          >起点</text>
        </g>

        <!-- 轨迹线（渐变 + 末端方向箭头 + 光晕） -->
        <g v-if="trajProjected.length > 1" class="traj-g">
          <polyline :points="trajPolyline" fill="none" stroke="#1677ff" stroke-opacity="0.22"
            stroke-width="6" stroke-linejoin="round" stroke-linecap="round" :filter="url.softGlow" />
          <polyline :points="trajPolyline" fill="none" :stroke="url.traj" stroke-width="2.6"
            stroke-linejoin="round" stroke-linecap="round" :marker-end="url.arrow"
            vector-effect="non-scaling-stroke" />
        </g>

        <!-- 设备点（类型图标 + 实时脉冲环 + 名称底纹） -->
        <g v-for="d in deviceMarks" :key="d.device_no" class="dev-g" :class="{ live: d.live }">
          <template v-if="d.pr">
            <circle v-if="d.live" :cx="d.pr.x" :cy="d.pr.y" r="16" fill="none" stroke="#52c41a"
              stroke-width="3" class="dev-halo" />
            <circle :cx="d.pr.x" :cy="d.pr.y" r="11" :fill="d.color" fill-opacity="0.18" />
            <circle :cx="d.pr.x" :cy="d.pr.y" r="9" :fill="d.color" stroke="#fff" stroke-width="2.5"
              class="dev-core" />
            <g :transform="`translate(${d.pr.x},${d.pr.y})`" fill="#fff">
              <template v-if="d.device_type === 'anti_intrusion'">
                <path d="M0,-4.2 L3.4,-2.4 V1 C3.4,2.6 1.7,3.9 0,4.7 C-1.7,3.9 -3.4,2.6 -3.4,1 V-2.4 Z" />
              </template>
              <template v-else-if="d.device_type === 'train_approach'">
                <rect x="-3.6" y="-3.2" width="7.2" height="6.4" rx="2" />
                <circle cx="-1.5" cy="-1" r="0.9" :fill="d.color" />
                <circle cx="1.5" cy="-1" r="0.9" :fill="d.color" />
              </template>
              <template v-else>
                <circle r="2.3" />
                <path d="M0,-4.6 V-3.1 M0,3.1 V4.6 M-4.6,0 H-3.1 M3.1,0 H4.6" stroke="#fff" stroke-width="1.2" fill="none" />
              </template>
            </g>
            <text :x="d.pr.x + 14" :y="d.pr.y + 4" font-size="12" fill="#1f2d3d" font-weight="500"
              paint-order="stroke" stroke="#fff" stroke-width="3.2" stroke-linejoin="round">
              {{ d.name }}<tspan v-if="d.live" fill="#52c41a">·实时</tspan>
            </text>
          </template>
        </g>

        <!-- 移动标记（拖尾 + 光晕 + 核心） -->
        <g v-if="movingProj">
          <polyline v-if="trailPolyline" :points="trailPolyline" fill="none" stroke="#1677ff"
            stroke-width="3" stroke-opacity="0.4" stroke-linecap="round" :filter="url.softGlow" />
          <circle :cx="movingProj.x" :cy="movingProj.y" r="11" fill="#1677ff" fill-opacity="0.16" />
          <circle :cx="movingProj.x" :cy="movingProj.y" r="7" fill="#1677ff" stroke="#fff" stroke-width="2.5"
            class="moving-core" />
        </g>

        <!-- 告警联动高亮环（脉冲） -->
        <g v-if="highlightProj">
          <circle :cx="highlightProj.x" :cy="highlightProj.y" r="16"
            fill="none" stroke="#f5222d" stroke-width="3" class="pulse-ring" />
          <circle :cx="highlightProj.x" :cy="highlightProj.y" r="4" fill="#f5222d" />
        </g>

        <!-- 测距：折线 + 顶点 + 分段/累计标签 -->
        <g v-if="measureProjected.length">
          <polyline v-if="measureProjected.length > 1" :points="measurePolyline"
            fill="none" stroke="#722ed1" stroke-width="2.5" stroke-dasharray="6 4"
            stroke-linejoin="round" stroke-linecap="round" />
          <circle v-for="(p, i) in measureProjected" :key="'mp' + i"
            :cx="p.x" :cy="p.y" r="4" fill="#722ed1" stroke="#fff" stroke-width="1.5" />
          <g v-for="(l, i) in measureLabels" :key="'ml' + i">
            <text :x="l.x" :y="l.y" font-size="11" fill="#fff" text-anchor="middle"
              paint-order="stroke" stroke="#722ed1" stroke-width="7" stroke-linejoin="round">
              {{ l.text }}
            </text>
          </g>
        </g>

        <!-- 经纬度刻度标签 -->
        <g font-size="10" fill="#8a93a3">
          <text v-for="t in lngTicks" :key="'lt' + t.x" :x="t.x" :y="VB_H - PAD.b + 14" text-anchor="middle">
            {{ t.label }}
          </text>
          <text v-for="t in latTicks" :key="'lt2' + t.y" :x="PAD.l - 6" :y="t.y + 3" text-anchor="end">
            {{ t.label }}
          </text>
        </g>

        <!-- 图例 -->
        <g class="legend" pointer-events="none" :transform="`translate(${PR - 92}, ${PB - 74})`">
          <rect x="0" y="0" width="88" height="66" rx="4" fill="#ffffff" fill-opacity="0.92"
            stroke="#dbe3ee" stroke-width="1" />
          <line x1="9" y1="14" x2="28" y2="14" class="legend-river" />
          <text x="34" y="17" class="legend-txt">河流</text>
          <line x1="9" y1="28" x2="28" y2="28" class="legend-rail" />
          <text x="34" y="31" class="legend-txt">铁路</text>
          <line x1="9" y1="42" x2="28" y2="42" class="legend-road" />
          <text x="34" y="45" class="legend-txt">道路</text>
          <rect x="9" y="53" width="19" height="9" rx="2" class="legend-park" />
          <text x="34" y="61" class="legend-txt">绿地</text>
        </g>

        <!-- 比例尺 -->
        <g class="scale-bar">
          <line :x1="scaleBar.x" :y1="scaleBar.y" :x2="scaleBar.x + scaleBar.px" :y2="scaleBar.y"
            stroke="#475569" stroke-width="2" />
          <line :x1="scaleBar.x" :y1="scaleBar.y - 4" :x2="scaleBar.x" :y2="scaleBar.y + 4" stroke="#475569" stroke-width="2" />
          <line :x1="scaleBar.x + scaleBar.px" :y1="scaleBar.y - 4" :x2="scaleBar.x + scaleBar.px" :y2="scaleBar.y + 4" stroke="#475569" stroke-width="2" />
          <text :x="scaleBar.x + scaleBar.px / 2" :y="scaleBar.y - 7" font-size="10" fill="#475569"
            text-anchor="middle" font-weight="600">{{ scaleBar.label }}</text>
        </g>

        <!-- 指北针 -->
        <g :transform="`translate(${VB_W - PAD.r - 18}, ${PAD.t + 18})`" class="compass">
          <circle r="14" fill="#fff" fill-opacity="0.92" stroke="#cbd5e1" stroke-width="1" />
          <path d="M0,-10 L4,4 L0,1 L-4,4 Z" fill="#cf1322" />
          <path d="M0,10 L4,-4 L0,-1 L-4,-4 Z" fill="#94a3b8" />
          <text x="0" y="-15" font-size="10" fill="#cf1322" text-anchor="middle" font-weight="700">N</text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.map-panel {
  position: relative;
  width: 100%;
}
.map-canvas {
  width: 100%;
  border-radius: 6px;
  overflow: hidden;
}
.map-tools {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.9);
  padding: 4px 6px;
  border-radius: 6px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
}
.tool-btn {
  border: 1px solid #d9dee6;
  background: #fff;
  color: #4a5568;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.tool-btn:hover:not(:disabled) {
  border-color: #722ed1;
  color: #722ed1;
}
.tool-btn.active {
  background: #722ed1;
  border-color: #722ed1;
  color: #fff;
}
.tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.tool-total {
  font-size: 12px;
  font-weight: 600;
  color: #722ed1;
  padding: 0 4px;
}
.mock-svg.measuring {
  cursor: crosshair;
}
.mock-svg.drawing {
  cursor: crosshair;
}
.tool-btn.primary {
  background: #1677ff;
  border-color: #1677ff;
  color: #fff;
}
.tool-btn.primary:hover:not(:disabled) {
  background: #4096ff;
  border-color: #4096ff;
}
.draw-hint {
  color: #1677ff;
}
.fence-g {
  cursor: pointer;
}
.fence-g:hover polygon {
  fill-opacity: 0.34;
  stroke-width: 2.5;
}
.fence-g.measuring {
  cursor: crosshair;
}
.fence-hint {
  position: absolute;
  bottom: 8px;
  left: 8px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #d9480f;
  background: rgba(255, 255, 255, 0.9);
  padding: 3px 8px;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  pointer-events: none;
}
.pulse-ring {
  transform-box: fill-box;
  transform-origin: center;
  animation: pulse 1.2s ease-out infinite;
}
@keyframes pulse {
  0% {
    opacity: 0.9;
    transform: scale(0.6);
  }
  100% {
    opacity: 0;
    transform: scale(1.4);
  }
}
.map-mock {
  position: relative;
  width: 100%;
  border: 1px solid #dbe3ee;
  border-radius: 6px;
  overflow: hidden;
  background: #eef3fb;
}
.mock-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #5a6573;
  background: rgba(255, 255, 255, 0.85);
  padding: 3px 8px;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.mock-svg {
  width: 100%;
  height: 100%;
  display: block;
}
.dev-g {
  cursor: pointer;
}
.dev-core {
  transform-box: fill-box;
  transform-origin: center;
  transition: transform 0.15s;
}
.dev-g:hover .dev-core {
  transform: scale(1.14);
}
.dev-halo {
  transform-box: fill-box;
  transform-origin: center;
  animation: devHalo 1.8s ease-out infinite;
}
@keyframes devHalo {
  0% {
    opacity: 0.85;
    transform: scale(0.5);
  }
  100% {
    opacity: 0;
    transform: scale(1.7);
  }
}
.fence-poly {
  transition: fill-opacity 0.15s, stroke-width 0.15s;
}
.fence-dash {
  animation: fenceFlow 1.1s linear infinite;
}
@keyframes fenceFlow {
  to {
    stroke-dashoffset: -24;
  }
}
.fence-g:hover .fence-poly {
  fill-opacity: 0.4;
  stroke-width: 2.6;
}
.moving-core {
  transform-box: fill-box;
  transform-origin: center;
  animation: movPulse 1.4s ease-in-out infinite;
}
@keyframes movPulse {
  0%,
  100% {
    filter: drop-shadow(0 0 1.5px #1677ff);
  }
  50% {
    filter: drop-shadow(0 0 5px #1677ff);
  }
}
.scale-bar text {
  font-family: inherit;
}
.compass {
  pointer-events: none;
}
/* ===== 真图质感底图（路网/地形/铁路） ===== */
.base-layer {
  pointer-events: none;
}
.park-fill {
  fill: #cdeccd;
  fill-opacity: 0.75;
  stroke: #a9d6a9;
  stroke-width: 1;
}
.lake-fill {
  fill: #aed2f2;
  fill-opacity: 0.7;
  stroke: #7fb4e6;
  stroke-width: 1.2;
}
.river-bank {
  stroke: #b7d6f2;
  stroke-width: 20;
  stroke-opacity: 0.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.river-core {
  stroke: #86b9e8;
  stroke-width: 11;
  stroke-opacity: 0.9;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.contour-line {
  stroke: #d8c4a3;
  stroke-width: 0.8;
  stroke-opacity: 0.55;
  stroke-dasharray: 2 3;
}
.rail-casing {
  stroke: #9aa0ab;
  stroke-width: 4.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.rail-core {
  stroke: #5b616c;
  stroke-width: 2.2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.rail-ties {
  stroke: #ffffff;
  stroke-width: 2.4;
  stroke-dasharray: 1.5 7;
  stroke-linecap: round;
}
.road-casing,
.road-core {
  stroke-linejoin: round;
  stroke-linecap: round;
}
.road-highway.road-casing {
  stroke: #f0b454;
  stroke-width: 8.5;
}
.road-highway.road-core {
  stroke: #ffffff;
  stroke-width: 4.2;
}
.road-arterial.road-casing {
  stroke: #c9d2de;
  stroke-width: 5;
}
.road-arterial.road-core {
  stroke: #fbfcfe;
  stroke-width: 2.8;
}
.road-minor.road-casing {
  stroke: #dde3ec;
  stroke-width: 3;
}
.road-minor.road-core {
  stroke: #ffffff;
  stroke-width: 1.6;
}
/* 图例 */
.legend-txt {
  font-size: 10px;
  fill: #5a6573;
}
.legend-river {
  stroke: #86b9e8;
  stroke-width: 4;
  stroke-linecap: round;
}
.legend-rail {
  stroke: #5b616c;
  stroke-width: 3;
}
.legend-road {
  stroke: #f0b454;
  stroke-width: 4;
}
.legend-park {
  fill: #cdeccd;
  stroke: #a9d6a9;
  stroke-width: 1;
}
</style>
