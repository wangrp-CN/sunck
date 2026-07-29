<script setup lang="ts">
// 响应式表格包装：窄屏（<=768px）强制最小宽度并横向滚动，避免 el-table 列被挤压换行。
// 用法：把原 <el-table ...>...</el-table> 的标签名换成 <ResponsiveTable ...>，列作为默认插槽传入。
// 通过 v-bind="$attrs" 透传 data/border/stripe/height/v-loading 等属性到内部 el-table。
// inheritAttrs=false：避免属性同时落到根 div（否则 v-loading 会在外层再叠加一层 loading）。
defineOptions({ inheritAttrs: false });
</script>

<template>
  <div class="table-scroll">
    <el-table v-bind="$attrs">
      <slot />
    </el-table>
  </div>
</template>

<style scoped>
.table-scroll {
  width: 100%;
  overflow-x: auto;
}
/* 仅在窄屏强制最小宽度，触发横向滚动；桌面端表格自适应容器宽度 */
@media (max-width: 768px) {
  .table-scroll :deep(.el-table) {
    min-width: 720px;
  }
}
</style>
