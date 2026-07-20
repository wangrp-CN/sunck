<script setup lang="ts">
import { ref, computed } from "vue";
import { uploadMedia } from "@/api/media";

const props = withDefaults(
  defineProps<{
    modelValue: string[] | null;
    prefix?: string;
    accept?: string;
    maxSizeMB?: number;
    disabled?: boolean;
  }>(),
  {
    prefix: "",
    accept: "image/*,video/*",
    maxSizeMB: 100,
    disabled: false,
  },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: string[]): void;
  (e: "change", v: string[]): void;
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);

const items = computed(() => props.modelValue ?? []);

function mediaType(url: string): "image" | "video" | "file" {
  const ext = (url.split("?")[0].split("#")[0].split(".").pop() || "").toLowerCase();
  if (["jpg", "jpeg", "png", "gif", "webp", "bmp"].includes(ext)) return "image";
  if (["mp4", "webm", "mov", "avi", "mkv"].includes(ext)) return "video";
  return "file";
}

function trigger() {
  if (props.disabled || uploading.value) return;
  fileInput.value?.click();
}

async function onChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = input.files;
  if (!files || files.length === 0) return;
  const maxBytes = props.maxSizeMB * 1024 * 1024;
  const oversize = Array.from(files).filter((f) => f.size > maxBytes);
  if (oversize.length) {
    ElMessage.error(`存在超过 ${props.maxSizeMB}MB 的文件：${oversize.map((f) => f.name).join("、")}`);
    input.value = "";
    return;
  }
  uploading.value = true;
  try {
    const metas = await uploadMedia(Array.from(files), props.prefix);
    const urls = metas.map((m) => m.url);
    const next = [...items.value, ...urls];
    emit("update:modelValue", next);
    emit("change", next);
    ElMessage.success(`已上传 ${urls.length} 个文件`);
  } catch (err: any) {
    ElMessage.error(err?.message || "上传失败");
  } finally {
    uploading.value = false;
    input.value = "";
  }
}

function removeAt(idx: number) {
  const next = items.value.filter((_, i) => i !== idx);
  emit("update:modelValue", next);
  emit("change", next);
}
</script>

<template>
  <div class="media-upload">
    <div class="toolbar">
      <el-button
        type="primary"
        plain
        size="small"
        :disabled="disabled || uploading"
        @click="trigger"
      >
        {{ uploading ? "上传中…" : "上传图片/视频" }}
      </el-button>
      <span class="hint">单文件 ≤ {{ maxSizeMB }}MB，可多选</span>
      <input
        ref="fileInput"
        type="file"
        :accept="accept"
        multiple
        hidden
        @change="onChange"
      />
    </div>

    <div v-if="items.length" class="grid">
      <div v-for="(url, idx) in items" :key="url + idx" class="cell">
        <img v-if="mediaType(url) === 'image'" :src="url" class="thumb" alt="媒体" />
        <video v-else-if="mediaType(url) === 'video'" :src="url" class="thumb" controls preload="metadata" />
        <div v-else class="file-box">文件</div>
        <el-button
          v-if="!disabled"
          class="del"
          type="danger"
          size="small"
          circle
          @click="removeAt(idx)"
        >
          ✕
        </el-button>
      </div>
    </div>
    <div v-else class="empty">暂无媒体</div>
  </div>
</template>

<style scoped>
.media-upload { width: 100%; }
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.hint { color: #909399; font-size: 12px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 10px;
}
.cell {
  position: relative;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  background: #f5f7fa;
  aspect-ratio: 1 / 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.thumb { width: 100%; height: 100%; object-fit: cover; display: block; }
.file-box {
  font-size: 13px;
  color: #606266;
  padding: 8px;
  text-align: center;
}
.del {
  position: absolute;
  top: 4px;
  right: 4px;
  padding: 2px 4px;
  font-size: 12px;
}
.empty { color: #c0c4cc; font-size: 13px; padding: 12px 0; }
</style>
