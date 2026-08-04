<script setup lang="ts">
/**
 * 统一表格分页组件。
 *
 * 统一以下交互，避免各列表页各写一套：
 * 1. 每页条数下拉：默认 [10, 20, 30, 50, 100]；
 * 2. 切换每页条数后自动回到第 1 页并立即刷新列表（无需手动再点分页）；
 * 3. 多选场景在左侧展示「已选 N 项」；
 * 4. 文案由全局 el-config-provider(zh-cn) 统一中文化。
 *
 * 用法：
 *   <TablePager v-model:page="page" v-model:size="size" :total="total" @change="load" />
 */
const props = withDefaults(
  defineProps<{
    /** 当前页码，配合 v-model:page */
    page: number;
    /** 每页条数，配合 v-model:size */
    size: number;
    /** 总条数 */
    total: number;
    /** 多选场景下的已选条数；大于 0 时展示「已选 N 项」 */
    selected?: number;
    /** 分页按钮背景样式 */
    background?: boolean;
    /** 小尺寸（用于抽屉、侧栏等紧凑容器） */
    small?: boolean;
    /** 每页条数候选项 */
    pageSizes?: number[];
  }>(),
  {
    selected: 0,
    background: true,
    small: false,
    pageSizes: () => [10, 20, 30, 50, 100],
  },
);

const emit = defineEmits<{
  (e: "update:page", value: number): void;
  (e: "update:size", value: number): void;
  /** 页码或每页条数变化后触发，父组件在此重新拉取列表 */
  (e: "change"): void;
}>();

/** 切换每页条数：重置到第 1 页并立即刷新 */
function handleSizeChange(value: number) {
  if (value === props.size) return;
  emit("update:size", value);
  emit("update:page", 1);
  emit("change");
}

/**
 * 切换页码。
 * el-pagination 在每页条数变化导致总页数收缩时也会补发 current-change，
 * 此处用「页码未变则不重复请求」拦截，避免一次操作触发两次列表加载。
 */
function handleCurrentChange(value: number) {
  if (value === props.page) return;
  emit("update:page", value);
  emit("change");
}
</script>

<template>
  <div class="table-pager">
    <span v-if="selected > 0" class="table-pager__selected">
      已选 <b>{{ selected }}</b> 项
    </span>
    <el-pagination
      :current-page="page"
      :page-size="size"
      :total="total"
      :page-sizes="pageSizes"
      :background="background"
      :small="small"
      layout="total, sizes, prev, pager, next, jumper"
      @size-change="handleSizeChange"
      @current-change="handleCurrentChange"
    />
  </div>
</template>

<style scoped>
.table-pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
}
.table-pager__selected {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}
.table-pager__selected b {
  color: var(--el-color-primary);
  margin: 0 2px;
}
</style>
