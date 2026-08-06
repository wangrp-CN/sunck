<script setup lang="ts">
/**
 * 统一批量操作工具条。
 *
 * 统一以下交互，避免各列表页各写一套：
 * 1. 实时展示「已选择 N 项」（与 TablePager 文案保持一致）；
 * 2. 批量删除按钮：未选中任何行时禁用，点击后由父组件确认并调用批量删除接口；
 * 3. 清空选择按钮：未选中任何行时禁用；
 * 4. 默认插槽可插入模块特有的批量动作（如告警的「批量处置」）。
 *
 * 用法：
 *   <BatchActions
 *     :selected="selectedRows.length"
 *     :loading="batchDeleting"
 *     @batch-delete="onBatchDelete"
 *     @clear="clearSelection"
 *   />
 */
withDefaults(
  defineProps<{
    /** 已选条数 */
    selected: number;
    /** 批量删除进行中（按钮 loading） */
    loading?: boolean;
    /** 批量删除按钮文案 */
    deleteText?: string;
    /** 清空选择按钮文案 */
    clearText?: string;
    /** 是否展示批量删除按钮（无删除权限时传 false） */
    showDelete?: boolean;
  }>(),
  {
    loading: false,
    deleteText: "批量删除",
    clearText: "清空选择",
    showDelete: true,
  },
);

const emit = defineEmits<{
  /** 点击批量删除 */
  (e: "batch-delete"): void;
  /** 点击清空选择 */
  (e: "clear"): void;
}>();
</script>

<template>
  <div class="batch-actions">
    <span class="batch-actions__count">
      已选择 <b>{{ selected }}</b> 项
    </span>
    <!-- 批量删除 / 清空选择 成组靠左，与计数等相邻元素保持适中间距，避免误触且布局协调 -->
    <div class="batch-actions__buttons">
      <el-button
        v-if="showDelete"
        type="danger"
        :disabled="selected === 0"
        :loading="loading"
        class="batch-actions__delete"
        @click="emit('batch-delete')"
      >
        {{ deleteText }}
      </el-button>
      <el-button
        type="default"
        :disabled="selected === 0"
        class="batch-actions__clear"
        @click="emit('clear')"
      >
        {{ clearText }}
      </el-button>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.batch-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.batch-actions__count {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}
.batch-actions__count b {
  color: var(--el-color-primary);
  font-size: 15px;
  margin: 0 2px;
}
.batch-actions__buttons {
  display: flex;
  align-items: center;
  gap: 12px;
}
/* 「清空选择」实心按钮 + 加粗，视觉明显但不与危险色「批量删除」混淆 */
.batch-actions__clear {
  font-weight: 600;
}
</style>
