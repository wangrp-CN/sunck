// 响应式断点组合式函数：在桌面/移动之间切换布局。
// 以 960px 为界（平板竖屏/手机走移动布局：侧栏抽屉化、表格横向滚动）。
import { onMounted, onUnmounted, ref } from "vue";

export const MOBILE_BREAKPOINT = 960;

/**
 * 返回当前视口宽度与是否移动端。
 * 组件卸载时自动解绑 resize 监听。
 */
export function useBreakpoint() {
  const width = ref(typeof window !== "undefined" ? window.innerWidth : 1280);
  const isMobile = ref(width.value <= MOBILE_BREAKPOINT);

  function update() {
    width.value = window.innerWidth;
    isMobile.value = width.value <= MOBILE_BREAKPOINT;
  }

  onMounted(() => window.addEventListener("resize", update));
  onUnmounted(() => window.removeEventListener("resize", update));

  return { width, isMobile, MOBILE_BREAKPOINT };
}
