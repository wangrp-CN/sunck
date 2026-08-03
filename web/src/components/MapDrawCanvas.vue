<script setup lang="ts">
/**
 * 地图手动绘制画布（自包含 SVG 交互地图，无需高德 Key）。
 *
 * 能力：
 * - 程序化生成稳定路网（网格主干 + 支路 + 对角线），同时作为「沿路画线」的路径图；
 * - 支持平移(拖拽)/缩放(滚轮或按钮)，经纬度 ↔ 画布坐标双向投影（GCJ-02）；
 * - 四种绘制模式：自由画点 / 坐标画点 / 自由画线 / 沿路画线（Dijkstra 最短路径吸附）；
 * - 渲染已保存标注（点/线）与当前草稿，草稿支持撤销与清空。
 */
import { computed, ref, watch } from "vue";
import type { DrawMode, LngLat, SavedDrawing } from "./map-draw.types";

const props = withDefaults(
  defineProps<{
    drawMode?: DrawMode;
    points?: number[][];
    saved?: SavedDrawing[];
    center?: LngLat;
    highlightId?: number | null;
    color?: string;
  }>(),
  {
    drawMode: "idle",
    points: () => [],
    saved: () => [],
    center: () => [116.397, 39.908] as LngLat,
    highlightId: null,
    color: "#f56c6c",
  },
);

const emit = defineEmits<{
  (e: "update:points", v: number[][]): void;
  (e: "pick", v: LngLat): void;
}>();

// ---------------------------------------------------------------- 画布与投影
const VB_W = 1000;
const VB_H = 620;

const BASE: LngLat = [props.center[0], props.center[1]];
const viewCenter = ref<LngLat>([BASE[0], BASE[1]]);
const spanLng = ref(0.09);

const latScale = computed(() => Math.max(0.2, Math.cos((viewCenter.value[1] * Math.PI) / 180)));
const spanLat = computed(() => (spanLng.value * latScale.value * VB_H) / VB_W);

function project(lng: number, lat: number): { x: number; y: number } {
  const [cLng, cLat] = viewCenter.value;
  const x = ((lng - (cLng - spanLng.value / 2)) / spanLng.value) * VB_W;
  const y = (1 - (lat - (cLat - spanLat.value / 2)) / spanLat.value) * VB_H;
  return { x, y };
}

function unproject(x: number, y: number): LngLat {
  const [cLng, cLat] = viewCenter.value;
  const lng = cLng - spanLng.value / 2 + (x / VB_W) * spanLng.value;
  const lat = cLat - spanLat.value / 2 + (1 - y / VB_H) * spanLat.value;
  return [round6(lng), round6(lat)];
}

function round6(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}

const EARTH_R = 6371008.8;
function haversine(a: number[], b: number[]): number {
  const p1 = (a[1] * Math.PI) / 180;
  const p2 = (b[1] * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((b[0] - a[0]) * Math.PI) / 180;
  const h =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function pathLength(pts: number[][]): number {
  let s = 0;
  for (let i = 1; i < pts.length; i++) s += haversine(pts[i - 1], pts[i]);
  return s;
}

function fmtLen(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`;
}

// ---------------------------------------------------------------- 路网生成
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const COLS = 9;
const ROWS = 7;
const NET_SPAN_LNG = 0.16;
const NET_SPAN_LAT = 0.072;

interface NetNode {
  lng: number;
  lat: number;
}

/** 网格节点（行列交叉点，带确定性抖动）→ 既是渲染顶点也是路径图节点 */
const netNodes: NetNode[] = (() => {
  const rnd = mulberry32(20260803);
  const cellLng = NET_SPAN_LNG / (COLS - 1);
  const cellLat = NET_SPAN_LAT / (ROWS - 1);
  const out: NetNode[] = [];
  for (let i = 0; i < COLS; i++) {
    for (let j = 0; j < ROWS; j++) {
      const jx = (rnd() - 0.5) * cellLng * 0.28;
      const jy = (rnd() - 0.5) * cellLat * 0.28;
      out.push({
        lng: BASE[0] - NET_SPAN_LNG / 2 + i * cellLng + jx,
        lat: BASE[1] - NET_SPAN_LAT / 2 + j * cellLat + jy,
      });
    }
  }
  return out;
})();

const nid = (i: number, j: number) => i * ROWS + j;

interface NetEdge {
  a: number;
  b: number;
}

/** 路网边：纵横主干 + 若干对角连接（保证图连通，可做最短路径） */
const netEdges: NetEdge[] = (() => {
  const out: NetEdge[] = [];
  for (let i = 0; i < COLS; i++)
    for (let j = 0; j < ROWS - 1; j++) out.push({ a: nid(i, j), b: nid(i, j + 1) });
  for (let j = 0; j < ROWS; j++)
    for (let i = 0; i < COLS - 1; i++) out.push({ a: nid(i, j), b: nid(i + 1, j) });
  const diag: [number, number][] = [
    [1, 1],
    [3, 2],
    [5, 0],
    [6, 3],
    [2, 4],
    [7, 1],
  ];
  for (const [i, j] of diag) {
    if (i + 1 < COLS && j + 1 < ROWS) out.push({ a: nid(i, j), b: nid(i + 1, j + 1) });
  }
  return out;
})();

/** 邻接表（权重=米） */
const adjacency: { to: number; w: number }[][] = (() => {
  const adj: { to: number; w: number }[][] = netNodes.map(() => []);
  for (const e of netEdges) {
    const na = netNodes[e.a];
    const nb = netNodes[e.b];
    const w = haversine([na.lng, na.lat], [nb.lng, nb.lat]);
    adj[e.a].push({ to: e.b, w });
    adj[e.b].push({ to: e.a, w });
  }
  return adj;
})();

/** Dijkstra：返回沿路节点 id 序列（含起终点） */
function shortestPath(from: number, to: number): number[] {
  if (from === to) return [from];
  const n = netNodes.length;
  const dist = new Array<number>(n).fill(Infinity);
  const prev = new Array<number>(n).fill(-1);
  const done = new Array<boolean>(n).fill(false);
  dist[from] = 0;
  for (let iter = 0; iter < n; iter++) {
    let u = -1;
    let best = Infinity;
    for (let k = 0; k < n; k++) {
      if (!done[k] && dist[k] < best) {
        best = dist[k];
        u = k;
      }
    }
    if (u < 0 || u === to) break;
    done[u] = true;
    for (const { to: v, w } of adjacency[u]) {
      if (dist[u] + w < dist[v]) {
        dist[v] = dist[u] + w;
        prev[v] = u;
      }
    }
  }
  if (dist[to] === Infinity) return [from, to];
  const path: number[] = [];
  for (let cur = to; cur !== -1; cur = prev[cur]) {
    path.unshift(cur);
    if (cur === from) break;
  }
  return path;
}

function nearestNode(lng: number, lat: number): number {
  let best = 0;
  let bestD = Infinity;
  for (let k = 0; k < netNodes.length; k++) {
    const d =
      (netNodes[k].lng - lng) ** 2 + ((netNodes[k].lat - lat) / latScale.value) ** 2;
    if (d < bestD) {
      bestD = d;
      best = k;
    }
  }
  return best;
}

const ROAD_NAMES_V = ["西环路", "文化大道", "站前一路", "科创大道", "铁建路", "青云街", "东兴路", "临港大道", "东环路"];
const ROAD_NAMES_H = ["北环大道", "和平街", "建设北路", "枢纽大道", "建设南路", "民安街", "南环大道"];

interface RoadPath {
  pts: string;
  width: number;
  arterial: boolean;
  label: string;
  lx: number;
  ly: number;
  vertical: boolean;
}

/** 渲染用道路（投影后的折线 + 名称锚点） */
const roadPaths = computed<RoadPath[]>(() => {
  const out: RoadPath[] = [];
  for (let i = 0; i < COLS; i++) {
    const arterial = i % 3 === 0;
    const pts: string[] = [];
    for (let j = 0; j < ROWS; j++) {
      const n = netNodes[nid(i, j)];
      const p = project(n.lng, n.lat);
      pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`);
    }
    const mid = project(netNodes[nid(i, Math.floor(ROWS / 2))].lng, netNodes[nid(i, Math.floor(ROWS / 2))].lat);
    out.push({
      pts: pts.join(" "),
      width: arterial ? 9 : 5,
      arterial,
      label: ROAD_NAMES_V[i] ?? "",
      lx: mid.x,
      ly: mid.y,
      vertical: true,
    });
  }
  for (let j = 0; j < ROWS; j++) {
    const arterial = j % 3 === 0;
    const pts: string[] = [];
    for (let i = 0; i < COLS; i++) {
      const n = netNodes[nid(i, j)];
      const p = project(n.lng, n.lat);
      pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`);
    }
    const midI = Math.floor(COLS / 2);
    const mid = project(netNodes[nid(midI, j)].lng, netNodes[nid(midI, j)].lat);
    out.push({
      pts: pts.join(" "),
      width: arterial ? 9 : 5,
      arterial,
      label: ROAD_NAMES_H[j] ?? "",
      lx: mid.x,
      ly: mid.y,
      vertical: false,
    });
  }
  for (const e of netEdges) {
    const na = netNodes[e.a];
    const nb = netNodes[e.b];
    const ia = Math.floor(e.a / ROWS);
    const ja = e.a % ROWS;
    const ib = Math.floor(e.b / ROWS);
    const jb = e.b % ROWS;
    if (ia === ib || ja === jb) continue; // 仅补对角线
    const pa = project(na.lng, na.lat);
    const pb = project(nb.lng, nb.lat);
    out.push({
      pts: `${pa.x.toFixed(1)},${pa.y.toFixed(1)} ${pb.x.toFixed(1)},${pb.y.toFixed(1)}`,
      width: 4,
      arterial: false,
      label: "",
      lx: 0,
      ly: 0,
      vertical: false,
    });
  }
  return out;
});

/** 街区面片（四个网格节点围成） */
const blocks = computed(() => {
  const out: { pts: string; tone: number }[] = [];
  for (let i = 0; i < COLS - 1; i++) {
    for (let j = 0; j < ROWS - 1; j++) {
      const quad = [nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)];
      const pts = quad
        .map((k) => {
          const p = project(netNodes[k].lng, netNodes[k].lat);
          return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        })
        .join(" ");
      out.push({ pts, tone: (i * 7 + j * 3) % 3 });
    }
  }
  return out;
});

/** 河流（贴合基准坐标的固定控制点） */
const riverPath = computed(() => {
  const ctrl: LngLat[] = [
    [BASE[0] - 0.09, BASE[1] - 0.028],
    [BASE[0] - 0.04, BASE[1] - 0.012],
    [BASE[0] + 0.005, BASE[1] - 0.026],
    [BASE[0] + 0.05, BASE[1] - 0.008],
    [BASE[0] + 0.095, BASE[1] - 0.02],
  ];
  const ps = ctrl.map(([lng, lat]) => project(lng, lat));
  let d = `M ${ps[0].x.toFixed(1)} ${ps[0].y.toFixed(1)}`;
  for (let i = 1; i < ps.length; i++) {
    const prev = ps[i - 1];
    const cur = ps[i];
    const cx = (prev.x + cur.x) / 2;
    d += ` Q ${cx.toFixed(1)} ${prev.y.toFixed(1)} ${cur.x.toFixed(1)} ${cur.y.toFixed(1)}`;
  }
  return d;
});

/** 铁路线（斜穿画面） */
const railwayPts = computed(() => {
  const ctrl: LngLat[] = [
    [BASE[0] - 0.095, BASE[1] + 0.03],
    [BASE[0] - 0.03, BASE[1] + 0.018],
    [BASE[0] + 0.03, BASE[1] + 0.026],
    [BASE[0] + 0.098, BASE[1] + 0.012],
  ];
  return ctrl
    .map(([lng, lat]) => {
      const p = project(lng, lat);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    })
    .join(" ");
});

// ---------------------------------------------------------------- 绘制状态
const isPointMode = computed(
  () => props.drawMode === "point-free" || props.drawMode === "point-coord",
);
const isLineMode = computed(
  () => props.drawMode === "line-free" || props.drawMode === "line-road",
);
const isRoadMode = computed(() => props.drawMode === "line-road");
const isDrawing = computed(() => props.drawMode !== "idle");

// 沿路模式的节点栈与分段栈（用于撤销）
const roadNodes = ref<number[]>([]);
const chunks = ref<number[][][]>([]);
const hoverNode = ref<number | null>(null);

watch(
  () => props.points,
  (v) => {
    if (!v || v.length === 0) {
      roadNodes.value = [];
      chunks.value = [];
    }
  },
  { deep: true },
);

watch(
  () => props.drawMode,
  () => {
    roadNodes.value = [];
    chunks.value = [];
    hoverNode.value = null;
  },
);

function flat(): number[][] {
  return chunks.value.flat();
}

function handlePick(lng: number, lat: number) {
  if (isPointMode.value) {
    emit("update:points", [[lng, lat]]);
    emit("pick", [lng, lat]);
    return;
  }
  if (props.drawMode === "line-free") {
    chunks.value = [...chunks.value, [[lng, lat]]];
    emit("update:points", flat());
    emit("pick", [lng, lat]);
    return;
  }
  if (props.drawMode === "line-road") {
    const node = nearestNode(lng, lat);
    if (roadNodes.value.length === 0) {
      roadNodes.value = [node];
      chunks.value = [[[round6(netNodes[node].lng), round6(netNodes[node].lat)]]];
    } else {
      const last = roadNodes.value[roadNodes.value.length - 1];
      if (last === node) return;
      const seg = shortestPath(last, node)
        .slice(1)
        .map((k) => [round6(netNodes[k].lng), round6(netNodes[k].lat)]);
      if (seg.length === 0) return;
      roadNodes.value = [...roadNodes.value, node];
      chunks.value = [...chunks.value, seg];
    }
    emit("update:points", flat());
    emit("pick", [round6(netNodes[node].lng), round6(netNodes[node].lat)]);
  }
}

function undo() {
  if (isPointMode.value) {
    emit("update:points", []);
    return;
  }
  if (chunks.value.length === 0) return;
  chunks.value = chunks.value.slice(0, -1);
  if (isRoadMode.value) roadNodes.value = roadNodes.value.slice(0, -1);
  emit("update:points", flat());
}

function clearDraft() {
  roadNodes.value = [];
  chunks.value = [];
  hoverNode.value = null;
  emit("update:points", []);
}

// ---------------------------------------------------------------- 交互
const svgEl = ref<SVGSVGElement | null>(null);
const pressing = ref(false);
const panned = ref(false);
const startPos = ref<{ x: number; y: number } | null>(null);
const cursorLngLat = ref<LngLat | null>(null);

function toViewBox(evt: MouseEvent): { x: number; y: number } | null {
  const svg = svgEl.value;
  if (!svg || typeof svg.getScreenCTM !== "function") return null;
  const ctm = svg.getScreenCTM();
  if (!ctm) return null;
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX;
  pt.y = evt.clientY;
  const loc = pt.matrixTransform(ctm.inverse());
  return { x: loc.x, y: loc.y };
}

function onDown(evt: MouseEvent) {
  pressing.value = true;
  panned.value = false;
  startPos.value = { x: evt.clientX, y: evt.clientY };
}

function onMove(evt: MouseEvent) {
  const loc = toViewBox(evt);
  if (loc) {
    cursorLngLat.value = unproject(loc.x, loc.y);
    if (isRoadMode.value) hoverNode.value = nearestNode(cursorLngLat.value[0], cursorLngLat.value[1]);
  }
  if (!pressing.value || !startPos.value) return;
  const dx = evt.clientX - startPos.value.x;
  const dy = evt.clientY - startPos.value.y;
  if (!panned.value && Math.abs(dx) + Math.abs(dy) < 5) return;
  panned.value = true;
  const rect = svgEl.value?.getBoundingClientRect();
  const w = rect?.width || VB_W;
  const h = rect?.height || VB_H;
  viewCenter.value = [
    viewCenter.value[0] - (dx / w) * spanLng.value,
    viewCenter.value[1] + (dy / h) * spanLat.value,
  ];
  startPos.value = { x: evt.clientX, y: evt.clientY };
}

function onUp(evt: MouseEvent) {
  const wasPanned = panned.value;
  pressing.value = false;
  startPos.value = null;
  if (wasPanned || !isDrawing.value) return;
  const loc = toViewBox(evt);
  if (!loc) return;
  const [lng, lat] = unproject(loc.x, loc.y);
  handlePick(lng, lat);
}

function onLeave() {
  pressing.value = false;
  startPos.value = null;
  cursorLngLat.value = null;
  hoverNode.value = null;
}

function onWheel(evt: WheelEvent) {
  const factor = evt.deltaY > 0 ? 1.18 : 1 / 1.18;
  spanLng.value = Math.min(0.4, Math.max(0.004, spanLng.value * factor));
}

function zoom(dir: 1 | -1) {
  spanLng.value = Math.min(0.4, Math.max(0.004, spanLng.value * (dir > 0 ? 1 / 1.3 : 1.3)));
}

function resetView() {
  viewCenter.value = [BASE[0], BASE[1]];
  spanLng.value = 0.09;
}

function focusOn(pts: number[][]) {
  if (!pts || pts.length === 0) return;
  let minLng = Infinity;
  let maxLng = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const [lng, lat] of pts) {
    minLng = Math.min(minLng, lng);
    maxLng = Math.max(maxLng, lng);
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
  }
  viewCenter.value = [(minLng + maxLng) / 2, (minLat + maxLat) / 2];
  const need = Math.max(maxLng - minLng, (maxLat - minLat) / latScale.value) * 2.2;
  spanLng.value = Math.min(0.4, Math.max(0.004, need || 0.02));
}

defineExpose({ undo, clearDraft, focusOn, resetView, project, unproject });

// ---------------------------------------------------------------- 渲染数据
const draftProjected = computed(() =>
  (props.points || []).map(([lng, lat]) => project(lng, lat)),
);
const draftPolyline = computed(() =>
  draftProjected.value.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "),
);
const draftLength = computed(() => pathLength(props.points || []));

const savedShapes = computed(() =>
  (props.saved || [])
    .filter((s) => Array.isArray(s.points) && s.points.length > 0)
    .map((s) => {
      const proj = s.points.map(([lng, lat]) => project(lng, lat));
      return {
        id: s.id,
        name: s.name,
        kind: s.kind,
        color: s.color || (s.kind === "point" ? "#409eff" : "#67c23a"),
        head: proj[0],
        polyline: proj.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "),
        active: props.highlightId === s.id,
      };
    }),
);

const roadNodeDots = computed(() => {
  if (!isRoadMode.value) return [] as { x: number; y: number; id: number }[];
  return netNodes.map((n, k) => {
    const p = project(n.lng, n.lat);
    return { x: p.x, y: p.y, id: k };
  });
});

const hoverDot = computed(() => {
  if (hoverNode.value === null) return null;
  const n = netNodes[hoverNode.value];
  return project(n.lng, n.lat);
});

/** 比例尺：画布 160px 对应的实际距离 */
const scaleText = computed(() => {
  const left = unproject(0, VB_H / 2);
  const right = unproject(160, VB_H / 2);
  return fmtLen(haversine(left, right));
});

const modeHint = computed(() => {
  switch (props.drawMode) {
    case "point-free":
      return "在地图上单击放置标注点，可拖拽平移、滚轮缩放";
    case "point-coord":
      return "在右侧输入经纬度定位标注点，也可直接单击地图取点";
    case "line-free":
      return "依次单击地图添加折点，形成自由折线";
    case "line-road":
      return "单击道路交叉口，系统自动沿道路生成最短路径";
    default:
      return "选择上方绘制模式后即可在地图上标注";
  }
});
</script>

<template>
  <div class="draw-canvas" :class="{ 'is-drawing': isDrawing }">
    <svg
      ref="svgEl"
      class="canvas-svg"
      :viewBox="`0 0 ${VB_W} ${VB_H}`"
      preserveAspectRatio="xMidYMid slice"
      @mousedown="onDown"
      @mousemove="onMove"
      @mouseup="onUp"
      @mouseleave="onLeave"
      @wheel.prevent="onWheel"
    >
      <defs>
        <linearGradient id="dcBg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#eef3ec" />
          <stop offset="100%" stop-color="#e6ece6" />
        </linearGradient>
        <filter id="dcHalo" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-color="#ffffff" flood-opacity="0.9" />
        </filter>
      </defs>

      <rect :width="VB_W" :height="VB_H" fill="url(#dcBg)" />

      <!-- 街区 -->
      <polygon
        v-for="(b, i) in blocks"
        :key="'b' + i"
        :points="b.pts"
        :fill="['#e4ebe3', '#e9eee7', '#dfe7de'][b.tone]"
        stroke="#d7e0d6"
        stroke-width="0.6"
      />

      <!-- 河流 -->
      <path :d="riverPath" fill="none" stroke="#bcd8ef" stroke-width="14" stroke-linecap="round" />
      <path :d="riverPath" fill="none" stroke="#a6cbe8" stroke-width="8" stroke-linecap="round" />

      <!-- 铁路 -->
      <polyline :points="railwayPts" fill="none" stroke="#8d949c" stroke-width="5" />
      <polyline
        :points="railwayPts"
        fill="none"
        stroke="#ffffff"
        stroke-width="2.4"
        stroke-dasharray="9 7"
      />

      <!-- 道路：外描边 + 路面 -->
      <polyline
        v-for="(rd, i) in roadPaths"
        :key="'rc' + i"
        :points="rd.pts"
        fill="none"
        stroke="#cfd8cd"
        :stroke-width="rd.width + 3"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <polyline
        v-for="(rd, i) in roadPaths"
        :key="'rf' + i"
        :points="rd.pts"
        fill="none"
        :stroke="rd.arterial ? '#ffffff' : '#f7f9f6'"
        :stroke-width="rd.width"
        stroke-linecap="round"
        stroke-linejoin="round"
      />

      <!-- 道路名 -->
      <template v-for="(rd, i) in roadPaths" :key="'rl' + i">
        <text
          v-if="rd.arterial && rd.label"
          :x="rd.lx"
          :y="rd.ly - 4"
          class="road-label"
          text-anchor="middle"
          filter="url(#dcHalo)"
        >
          {{ rd.label }}
        </text>
      </template>

      <!-- 沿路模式：可吸附交叉口 -->
      <template v-if="isRoadMode">
        <circle
          v-for="d in roadNodeDots"
          :key="'nd' + d.id"
          :cx="d.x"
          :cy="d.y"
          r="3"
          fill="#ffffff"
          stroke="#909399"
          stroke-width="1"
          opacity="0.85"
        />
        <circle
          v-if="hoverDot"
          :cx="hoverDot.x"
          :cy="hoverDot.y"
          r="7"
          fill="none"
          stroke="#e6a23c"
          stroke-width="2.5"
        />
      </template>

      <!-- 已保存标注 -->
      <template v-for="s in savedShapes" :key="'s' + s.id">
        <polyline
          v-if="s.kind === 'line'"
          :points="s.polyline"
          fill="none"
          :stroke="s.color"
          :stroke-width="s.active ? 6 : 4"
          stroke-linecap="round"
          stroke-linejoin="round"
          :opacity="s.active ? 1 : 0.85"
        />
        <g v-else :transform="`translate(${s.head.x}, ${s.head.y})`">
          <circle :r="s.active ? 8 : 6" :fill="s.color" stroke="#ffffff" stroke-width="2" />
        </g>
        <text
          :x="s.head.x + 10"
          :y="s.head.y - 8"
          class="shape-label"
          :class="{ active: s.active }"
          filter="url(#dcHalo)"
        >
          {{ s.name }}
        </text>
      </template>

      <!-- 草稿 -->
      <template v-if="(props.points || []).length > 0">
        <polyline
          v-if="isLineMode"
          :points="draftPolyline"
          fill="none"
          :stroke="props.color"
          stroke-width="5"
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-dasharray="10 6"
        />
        <circle
          v-for="(p, i) in draftProjected"
          :key="'dp' + i"
          :cx="p.x"
          :cy="p.y"
          :r="isPointMode ? 9 : 5"
          :fill="props.color"
          stroke="#ffffff"
          stroke-width="2"
        />
        <text
          v-if="isLineMode && draftProjected.length > 1"
          :x="draftProjected[draftProjected.length - 1].x + 10"
          :y="draftProjected[draftProjected.length - 1].y - 10"
          class="shape-label draft"
          filter="url(#dcHalo)"
        >
          {{ fmtLen(draftLength) }}
        </text>
      </template>
    </svg>

    <!-- HUD -->
    <div class="hud hud-tl">
      <span class="hint">{{ modeHint }}</span>
    </div>
    <div class="hud hud-tr">
      <button type="button" class="zbtn" title="放大" @click="zoom(1)">＋</button>
      <button type="button" class="zbtn" title="缩小" @click="zoom(-1)">－</button>
      <button type="button" class="zbtn wide" title="复位" @click="resetView">复位</button>
    </div>
    <div class="hud hud-bl">
      <span class="scale-bar" />
      <span class="scale-text">{{ scaleText }}</span>
    </div>
    <div class="hud hud-br">
      <span v-if="cursorLngLat" class="coord">
        {{ cursorLngLat[0].toFixed(6) }}, {{ cursorLngLat[1].toFixed(6) }}
      </span>
      <span v-else class="coord muted">GCJ-02 坐标</span>
    </div>
  </div>
</template>

<style scoped>
.draw-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 420px;
  border-radius: 10px;
  overflow: hidden;
  background: #eef3ec;
  border: 1px solid var(--el-border-color-light, #e4e7ed);
}
.canvas-svg {
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
  user-select: none;
}
.draw-canvas.is-drawing .canvas-svg {
  cursor: crosshair;
}
.road-label {
  font-size: 11px;
  fill: #6b7280;
  font-weight: 500;
}
.shape-label {
  font-size: 12px;
  fill: #303133;
  font-weight: 600;
}
.shape-label.active {
  fill: #c45656;
}
.shape-label.draft {
  fill: #b88230;
}
.hud {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  pointer-events: none;
}
.hud-tl {
  top: 10px;
  left: 12px;
}
.hud-tr {
  top: 10px;
  right: 12px;
  pointer-events: auto;
}
.hud-bl {
  bottom: 10px;
  left: 12px;
}
.hud-br {
  bottom: 10px;
  right: 12px;
}
.hint,
.coord,
.scale-text {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 6px;
  padding: 3px 8px;
  color: #606266;
}
.coord.muted {
  color: #909399;
}
.scale-bar {
  display: inline-block;
  width: 160px;
  height: 6px;
  border: 1px solid #909399;
  border-top: none;
  background: rgba(255, 255, 255, 0.6);
}
.zbtn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.92);
  color: #606266;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.zbtn.wide {
  width: auto;
  padding: 0 10px;
  font-size: 12px;
}
.zbtn:hover {
  background: #fff;
  color: #409eff;
}
</style>
