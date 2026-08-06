<script setup lang="ts">
/**
 * 告警详情页（大屏子菜单）—— 严格按 Axure 原型「告警详情页.html」还原。
 *
 * 原型结构（1088×606 白底卡片，左表单 + 右地图）：
 *  - 标题「告警详情」（16px/600，对齐系统卡片标题规范）
 *  - 左列只读字段：项目名称 / 告警类型 / 围栏名称 / 告警信息 / 告警时间
 *    label 76px + el-input disabled，统一使用 Element Plus 主题令牌（#dcdfe6 边框 / #f5f7fa 只读底 / #606266 文字）
 *  - 原型有两个变体（同一页面按告警类型动态渲染，不是两个页面）：
 *      变体A「围栏告警」→ 含「围栏名称」行
 *      变体B「大机防侵限告警」→ 含「告警图片」「告警视频」行，
 *        输入框内叠加蓝色下划线链接「图片」「视频」，点击查看媒体
 *  - 「处理内容」多行文本框 300×81（选填，唯一可编辑控件）
 *  - 右侧地图容器（Element Plus 卡片描边风格），含 2px 系统危险色(#f56c6c)高亮框圈出告警位置 + 设备图标
 *  - 底部右对齐按钮：处理（Element Plus 主按钮 #409eff）/ 取消（默认按钮）
 *
 * 交互（原型字段说明表 u293/u346）：
 *  - 项目名称/告警类型/围栏名称/告警信息/告警时间：只读
 *  - 告警图片：点击可查看报警图片；告警视频：点击可查看报警视频
 *  - 处理内容：多行文本框，选填
 *  - 处理：标记当前告警为已处理，**向对应设备发出消警指令**，并返回原页面
 *          → 提交 handle_status="已消警"，后端 handle 端点据此经 command_service 下发
 *  - 取消：返回原页面
 *
 * 自包含约定：仅依赖告警自身接口 + 通用 MapPanel，不改动/耦合其他业务模块。
 */
import { ref, computed, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import MapPanel from "@/components/MapPanel.vue";
import {
  getAlarmDetail,
  getLatestAlarm,
  handleAlarm,
  alarmTypeLabel,
  type AlarmDetail,
} from "@/api/alarm";
import { fetchLocations } from "@/api/realtime";
import { fetchFences } from "@/api/fence";
import { mediaKeyFromUrl, resolvePresigned } from "@/utils/media";
import type { MapDevice, MapFence } from "@/types";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const submitting = ref(false);
const detail = ref<AlarmDetail | null>(null);
/** 处理内容：原型中唯一可编辑控件（多行文本框，选填） */
const handleContent = ref("");
const mapRef = ref<InstanceType<typeof MapPanel> | null>(null);

const alarmId = computed<number | null>(() => {
  const raw = route.params.id;
  return raw !== undefined && raw !== "" ? Number(raw) : null;
});

// ---------------------------------------------------------------------------
// 只读字段（严格对应原型左列，空值统一回显 "—"）
// ---------------------------------------------------------------------------
const dash = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

const projectName = computed(() => dash(detail.value?.project_name));
const alarmTypeText = computed(() => alarmTypeLabel(detail.value?.alarm_type));
const fenceName = computed(() => dash(detail.value?.fence_name));
const alarmInfo = computed(() => dash(detail.value?.alarm_info));

/** 告警时间：原型格式 2024-06-28 08:27:10（后端 ISO → 本地可读，不引三方库） */
const alarmTime = computed(() => {
  const raw = detail.value?.alarm_time;
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(raw);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
});

// ---------------------------------------------------------------------------
// 媒体：原型「告警图片 / 告警视频」两行。后端只有一个 media_urls 数组，
// 按扩展名切分为图片/视频两组；对应组为空时该行不渲染（还原变体A/变体B差异）。
// ---------------------------------------------------------------------------
const VIDEO_EXT = ["mp4", "webm", "mov", "avi", "mkv"];
function mediaType(url: string): "image" | "video" {
  const ext = (url.split("?")[0].split("#")[0].split(".").pop() || "").toLowerCase();
  return VIDEO_EXT.includes(ext) ? "video" : "image";
}
const mediaUrls = computed<string[]>(() =>
  Array.isArray(detail.value?.media_urls) ? detail.value!.media_urls! : [],
);
const images = computed(() => mediaUrls.value.filter((u) => mediaType(u) === "image"));
const videos = computed(() => mediaUrls.value.filter((u) => mediaType(u) === "video"));
/** 原始 url/key → MinIO 预签名直连地址（媒体非公开，必须换签名 URL 才能渲染） */
const mediaSrc = ref<Record<string, string>>({});

async function loadMediaSrc() {
  const list = mediaUrls.value;
  if (!list.length) {
    mediaSrc.value = {};
    return;
  }
  try {
    mediaSrc.value = await resolvePresigned(list.map((u) => mediaKeyFromUrl(u)));
  } catch {
    mediaSrc.value = {};
  }
}
/** 模板取签名地址（解析失败降级为空串，由 el-image/video 自行占位） */
const srcOf = (u: string) => mediaSrc.value[mediaKeyFromUrl(u)] || "";

// 媒体查看弹窗（原型：点击蓝色链接「图片」/「视频」查看）
const mediaDialog = ref(false);
const mediaDialogKind = ref<"image" | "video">("image");
const mediaDialogTitle = computed(() =>
  mediaDialogKind.value === "image" ? "告警图片" : "告警视频",
);
const mediaDialogList = computed(() =>
  mediaDialogKind.value === "image" ? images.value : videos.value,
);
function openMedia(kind: "image" | "video") {
  mediaDialogKind.value = kind;
  mediaDialog.value = true;
}

// ---------------------------------------------------------------------------
// 右侧地图：定位告警设备 + 圈出关联围栏（原型红色高亮框 3px #D9001B）
// ---------------------------------------------------------------------------
const mapDevices = ref<MapDevice[]>([]);
const mapFences = ref<MapFence[]>([]);
/** 告警设备是否已在地图上定位到（决定红色高亮框与提示文案） */
const located = computed(() => mapDevices.value.length > 0);

async function loadMapData() {
  const d = detail.value;
  mapDevices.value = [];
  mapFences.value = [];
  if (!d) return;

  // 设备打点：取该项目最新位置，仅保留本告警设备（原型地图只高亮告警对象）
  if (d.device_no) {
    try {
      const res = await fetchLocations(d.project_id ?? undefined);
      const hit = (res.items || []).find((x) => x.device_no === d.device_no);
      const pt = hit?.gcj02;
      if (hit && pt && pt.lng != null && pt.lat != null) {
        mapDevices.value = [
          {
            device_no: hit.device_no,
            name: hit.device_name || d.device_name || hit.device_no,
            device_type: hit.device_type,
            lng: pt.lng,
            lat: pt.lat,
            status: hit.status || "在线",
            live: false,
          },
        ];
      }
    } catch {
      mapDevices.value = [];
    }
  }

  // 关联围栏：告警只冗余了 fence_name（无 fence_id），按名称精确匹配上图
  if (d.fence_name) {
    try {
      const page = await fetchFences({ keyword: d.fence_name, page: 1, size: 20 });
      mapFences.value = (page.items || [])
        .filter((f) => f.name === d.fence_name && f.geometry_wkt)
        .map((f) => ({ id: f.id, name: f.name, geometry_wkt: f.geometry_wkt }));
    } catch {
      mapFences.value = [];
    }
  }

  // 上图后聚焦告警设备（真图弹跳定位 / 模拟图脉冲高亮）
  if (d.device_no && mapDevices.value.length) {
    await Promise.resolve();
    mapRef.value?.focusDevice(d.device_no);
  }
}

// ---------------------------------------------------------------------------
// 载入
// ---------------------------------------------------------------------------
/** 无 id 入口（菜单直达）：定位到最新一条待处理告警并 replace 到带 id 路由 */
async function ensureAlarm() {
  try {
    const latest = await getLatestAlarm();
    if (latest?.id) {
      router.replace({ name: "alarm-detail", params: { id: String(latest.id) } });
    } else {
      detail.value = null;
      ElMessage.warning("暂无告警记录");
    }
  } catch {
    detail.value = null;
  }
}

async function loadDetail() {
  if (alarmId.value == null || Number.isNaN(alarmId.value)) {
    await ensureAlarm();
    return;
  }
  loading.value = true;
  try {
    const data = await getAlarmDetail(alarmId.value);
    detail.value = data;
    handleContent.value = data.handle_content || "";
    await Promise.all([loadMediaSrc(), loadMapData()]);
  } catch (e: any) {
    detail.value = null;
    ElMessage.error(e?.message || "告警详情加载失败");
  } finally {
    loading.value = false;
  }
}

onMounted(loadDetail);
watch(alarmId, loadDetail);

// ---------------------------------------------------------------------------
// 底部按钮（原型字段说明表语义）
// ---------------------------------------------------------------------------
/** 已处理的告警不可重复处置，按钮置灰 */
const handled = computed(() => {
  const s = detail.value?.handle_status;
  return !!s && s !== "待处理";
});

/**
 * 处理：标记为已处理 + 向对应设备发出消警指令 + 返回原页面。
 * 提交 handle_status="已消警" —— 后端 /handle 端点识别该状态后
 * 经 command_service 下发 alarm=off 指令，正是原型要求的「发出消警指令」。
 */
async function onSubmit() {
  const d = detail.value;
  if (!d) return;
  submitting.value = true;
  try {
    await handleAlarm(d.id, {
      handle_status: "已消警",
      content: handleContent.value || null,
    });
    ElMessage.success("告警已处理，消警指令已下发");
    goBack();
  } catch (e: any) {
    ElMessage.error(e?.message || "处理失败");
  } finally {
    submitting.value = false;
  }
}

/** 取消 / 处理完成：返回原页面（无历史记录时兜底回告警列表） */
function goBack() {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push({ name: "alarms" });
  }
}
</script>

<template>
  <div v-loading="loading" class="alarm-detail">
    <el-card class="ad-card" shadow="never">
      <div class="ad-body">
        <!-- 左列：只读字段 + 处理内容（原型 label 70px / 控件 300px） -->
        <div class="ad-form">
          <div class="ad-row">
            <span class="ad-label">项目名称：</span>
            <el-input class="ad-input" :model-value="projectName" disabled />
          </div>

          <div class="ad-row">
            <span class="ad-label">告警类型：</span>
            <el-input class="ad-input" :model-value="alarmTypeText" disabled />
          </div>

          <!-- 变体A：围栏类告警才有「围栏名称」 -->
          <div v-if="detail?.fence_name" class="ad-row">
            <span class="ad-label">围栏名称：</span>
            <el-input class="ad-input" :model-value="fenceName" disabled />
          </div>

          <div class="ad-row">
            <span class="ad-label">告警信息：</span>
            <el-input class="ad-input" :model-value="alarmInfo" disabled />
          </div>

          <!-- 变体B：大机防侵限等带抓拍的告警才有「告警图片 / 告警视频」 -->
          <div v-if="images.length" class="ad-row">
            <span class="ad-label">告警图片：</span>
            <div class="ad-input ad-media-field">
              <a class="ad-media-link" @click="openMedia('image')">图片</a>
              <span v-if="images.length > 1" class="ad-media-count">×{{ images.length }}</span>
            </div>
          </div>

          <div v-if="videos.length" class="ad-row">
            <span class="ad-label">告警视频：</span>
            <div class="ad-input ad-media-field">
              <a class="ad-media-link" @click="openMedia('video')">视频</a>
              <span v-if="videos.length > 1" class="ad-media-count">×{{ videos.length }}</span>
            </div>
          </div>

          <div class="ad-row">
            <span class="ad-label">告警时间：</span>
            <el-input class="ad-input" :model-value="alarmTime" disabled />
          </div>

          <!-- 处理内容：原型唯一可编辑控件（多行文本框 300×81，选填） -->
          <div class="ad-row ad-row-area">
            <span class="ad-label">处理内容：</span>
            <el-input
              v-model="handleContent"
              class="ad-input ad-textarea"
              type="textarea"
              :rows="4"
              :disabled="handled"
              placeholder="选填"
              resize="none"
            />
          </div>
        </div>

        <!-- 右列：地图 + 红色高亮框（原型 673×507，框 3px #D9001B） -->
        <div class="ad-map">
          <MapPanel ref="mapRef" :devices="mapDevices" :fences="mapFences" height="100%" />
          <div v-if="located" class="ad-map-highlight">
            <span class="ad-map-tip">{{ detail?.device_name || detail?.device_no }}</span>
          </div>
          <div v-else class="ad-map-empty">该告警未关联可定位设备</div>
        </div>
      </div>

      <!-- 底部按钮：处理（主）/ 取消 -->
      <div class="ad-actions">
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!detail || handled"
          @click="onSubmit"
        >
          处理
        </el-button>
        <el-button @click="goBack">取消</el-button>
      </div>
    </el-card>

    <!-- 媒体查看弹窗：原型「点击可查看报警图片 / 报警视频」 -->
    <el-dialog v-model="mediaDialog" :title="mediaDialogTitle" width="720px">
      <div class="ad-media-gallery">
        <template v-if="mediaDialogKind === 'image'">
          <el-image
            v-for="u in mediaDialogList"
            :key="u"
            :src="srcOf(u)"
            :preview-src-list="mediaDialogList.map(srcOf).filter(Boolean)"
            fit="contain"
            class="ad-media-item"
          />
        </template>
        <template v-else>
          <video
            v-for="u in mediaDialogList"
            :key="u"
            :src="srcOf(u)"
            class="ad-media-item"
            controls
            preload="metadata"
          />
        </template>
        <el-empty v-if="!mediaDialogList.length" description="暂无媒体" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 统一对齐系统浅色 Element Plus 主题：白卡片 / 主色 #409eff / 边框 #dcdfe6 /
   文字 #303133|#606266|#909399 / 圆角 4px，与监控大屏主页、告警列表保持一致 */
.alarm-detail {
  padding: 8px;
}
.ad-body {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

/* 左列表单：label 76px + 控件 320px，行距对齐系统表单密度 */
.ad-form {
  flex: 0 0 396px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.ad-row {
  display: flex;
  align-items: center;
}
.ad-row-area {
  align-items: flex-start;
}
.ad-label {
  flex: 0 0 76px;
  font-size: 14px;
  color: var(--el-text-color-regular);
  text-align: left;
  line-height: 32px;
}
.ad-input {
  width: 320px;
}
/* 处理内容多行文本框：保留原型高度，圆角统一为 EP 基准 */
.ad-textarea :deep(.el-textarea__inner) {
  min-height: 81px;
}

/* 媒体展示框：与原型一致（只读框内叠主色链接），配色统一为 EP 只读态 */
.ad-media-field {
  height: 32px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 11px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  box-sizing: border-box;
}
.ad-media-link {
  color: var(--el-color-primary);
  text-decoration: underline;
  cursor: pointer;
  font-size: 14px;
  transition: color 0.15s;
}
.ad-media-link:hover {
  color: var(--el-color-primary-light-3);
}
.ad-media-count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

/* 右侧地图容器：Element Plus 卡片描边风格 */
.ad-map {
  flex: 1 1 auto;
  position: relative;
  height: 507px;
  min-width: 360px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--el-border-radius-base);
  overflow: hidden;
  background: var(--el-fill-color-blank);
}
/* 告警位置高亮框：使用系统危险色，语义化圈出告警对象 */
.ad-map-highlight {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 300px;
  height: 170px;
  transform: translate(-50%, -50%);
  border: 2px solid var(--el-color-danger);
  border-radius: var(--el-border-radius-base);
  pointer-events: none;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}
.ad-map-tip {
  margin-top: -11px;
  background: var(--el-color-danger);
  color: #fff;
  font-size: 12px;
  line-height: 22px;
  padding: 0 8px;
  border-radius: var(--el-border-radius-base);
  white-space: nowrap;
}
.ad-map-empty {
  position: absolute;
  left: 50%;
  top: 12px;
  transform: translateX(-50%);
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: var(--el-border-radius-base);
  pointer-events: none;
}

/* 底部按钮：右对齐，使用 EP 原生主/次按钮（不再自定义底色） */
.ad-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.ad-media-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.ad-media-item {
  width: 320px;
  max-height: 240px;
  background: var(--el-fill-color-light);
  border-radius: var(--el-border-radius-base);
}

/* 窄屏：地图下沉为整行，表单占满 */
@media (max-width: 960px) {
  .ad-body {
    flex-direction: column;
  }
  .ad-form {
    flex: 1 1 auto;
    width: 100%;
  }
  .ad-input {
    width: 100%;
    max-width: 320px;
  }
  .ad-map {
    width: 100%;
    height: 360px;
  }
}
</style>
