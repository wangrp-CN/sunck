<template>
  <div class="att-manager">
    <div class="att-toolbar">
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        :disabled="!entityId"
        :on-change="onPick"
        multiple
        accept="image/*,video/*"
      >
        <el-button :loading="uploading" size="small" type="primary" :icon="Upload">
          上传附件
        </el-button>
      </el-upload>
      <span class="att-hint">图片 / 视频，单文件 ≤ 100MB</span>
    </div>

    <div v-if="items.length" class="att-grid">
      <div v-for="it in items" :key="it.id" class="att-card">
        <img v-if="isImage(it)" :src="it.url" class="att-thumb" alt="附件" />
        <video
          v-else-if="isVideo(it)"
          :src="it.url"
          class="att-thumb"
          controls
          preload="metadata"
        />
        <div v-else class="att-file">文件</div>
        <div class="att-meta">
          <span class="att-name" :title="it.filename">{{ it.filename }}</span>
          <span class="att-size">{{ fmtSize(it.size) }}</span>
        </div>
        <el-button
          class="att-del"
          size="small"
          text
          type="danger"
          :icon="Delete"
          title="删除"
          @click="remove(it)"
        />
      </div>
    </div>
    <el-empty v-else description="暂无附件" :image-size="56" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from "vue";
import { Delete, Upload } from "@element-plus/icons-vue";
import {
  fetchAttachments,
  uploadAttachments,
  deleteAttachment,
} from "@/api/attachment";
import type { Attachment } from "@/types";

const props = defineProps<{
  entityType: string;
  entityId: number | null;
}>();

const items = ref<Attachment[]>([]);
const uploading = ref(false);

async function load() {
  if (!props.entityId) {
    items.value = [];
    return;
  }
  try {
    items.value = await fetchAttachments(props.entityType, props.entityId);
  } catch {
    items.value = [];
  }
}

async function onPick(_file: any, fileList: any[]) {
  const files = fileList.map((f) => f.raw).filter(Boolean) as File[];
  if (!files.length || !props.entityId) return;
  uploading.value = true;
  try {
    const added = await uploadAttachments(props.entityType, props.entityId, files);
    items.value.push(...added);
    ElMessage.success(`已上传 ${added.length} 个附件`);
  } catch (e: any) {
    ElMessage.error(e?.message || "上传失败");
  } finally {
    uploading.value = false;
  }
}

async function remove(it: Attachment) {
  await deleteAttachment(it.id);
  items.value = items.value.filter((x) => x.id !== it.id);
  ElMessage.success("已删除");
}

function isImage(a: Attachment) {
  return a.content_type.startsWith("image/");
}
function isVideo(a: Attachment) {
  return a.content_type.startsWith("video/");
}
function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

onMounted(load);
watch(() => props.entityId, load);
</script>

<style scoped>
.att-manager {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
  background: var(--el-fill-color-blank);
}
.att-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.att-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.att-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
}
.att-card {
  position: relative;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}
.att-thumb {
  width: 100%;
  height: 96px;
  object-fit: cover;
  display: block;
  background: #f5f5f5;
}
.att-file {
  width: 100%;
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  background: #f5f5f5;
}
.att-meta {
  padding: 4px 6px;
  font-size: 11px;
  display: flex;
  justify-content: space-between;
  gap: 6px;
}
.att-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.att-size {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.att-del {
  position: absolute;
  top: 2px;
  right: 2px;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 4px;
}
</style>
