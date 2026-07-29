<script setup lang="ts">
// 视频流播放器（深化⑧）：支持 HLS(.m3u8，hls.js)、MP4/WebM 原生播放；
// RTSP/RTMP 浏览器无法直接解码，给出提示。stream_url 来自通道登记。
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import type HlsType from "hls.js";

const props = withDefaults(defineProps<{ url?: string | null; autoplay?: boolean }>(), {
  url: null,
  autoplay: true,
});

const videoEl = ref<HTMLVideoElement | null>(null);
// hls.js 实例（动态加载，仅 HLS 时创建；type-only import 不影响按需打包）
let hls: HlsType | null = null;

type Kind = "hls" | "native" | "unsupported" | "empty";
function detectKind(url: string | null | undefined): Kind {
  if (!url) return "empty";
  const u = url.toLowerCase();
  if (u.includes("m3u8")) return "hls";
  if (u.startsWith("rtsp://") || u.startsWith("rtmp://")) return "unsupported";
  if (/\.(mp4|webm|ogg|mov)(\?|$)/.test(u)) return "native";
  // 其余尝试按原生处理（部分浏览器支持直接播放）
  return "native";
}

const kind = ref<Kind>("empty");
const error = ref<string | null>(null);

async function load() {
  error.value = null;
  if (hls) {
    hls.destroy();
    hls = null;
  }
  const url = props.url;
  kind.value = detectKind(url);
  if (!url || kind.value === "empty" || kind.value === "unsupported") return;
  // v-if 渲染 <video> 需等一帧；immediate watch 在挂载前触发时 ref 也尚未就绪
  await nextTick();
  const el = videoEl.value;
  if (!el) return;

  if (kind.value === "hls") {
    // 动态加载 hls.js，避免无视频页面也打包该依赖
    try {
      const mod = await import("hls.js");
      const Hls = mod.default;
      if (Hls.isSupported()) {
        hls = new Hls({ lowLatencyMode: true });
        hls.loadSource(url);
        hls.attachMedia(el);
        if (props.autoplay) el.play().catch(() => undefined);
        return;
      }
      // Safari 原生支持 HLS
      el.src = url;
      if (props.autoplay) el.play().catch(() => undefined);
    } catch {
      error.value = "HLS 播放器加载失败（hls.js 未安装？）";
    }
  } else {
    // native
    el.src = url;
    if (props.autoplay) el.play().catch(() => undefined);
  }
}

watch(() => props.url, load, { immediate: true });

onBeforeUnmount(() => {
  if (hls) hls.destroy();
});
</script>

<template>
  <div class="player">
    <video
      v-if="kind === 'hls' || kind === 'native'"
      ref="videoEl"
      class="video"
      controls
      muted
      playsinline
    />
    <div v-if="kind === 'empty'" class="placeholder">暂无拉流地址</div>
    <div v-else-if="kind === 'unsupported'" class="placeholder">
      当前地址为 RTSP/RTMP，浏览器无法直接播放，请使用厂家客户端或转码为 HLS/MP4。
    </div>
    <div v-if="error" class="err">{{ error }}</div>
  </div>
</template>

<style scoped>
.player {
  width: 100%;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.video {
  width: 100%;
  max-height: 60vh;
  background: #000;
}
.placeholder {
  color: #c0c4cc;
  font-size: 13px;
  padding: 24px;
  text-align: center;
}
.err {
  position: absolute;
  color: #f56c6c;
  font-size: 12px;
}
</style>
