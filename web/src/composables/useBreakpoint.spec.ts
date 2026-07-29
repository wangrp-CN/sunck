// 响应式断点组合式函数测试
import { defineComponent, h } from "vue";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import { MOBILE_BREAKPOINT, useBreakpoint } from "@/composables/useBreakpoint";

const Probe = defineComponent({
  setup() {
    const { width, isMobile } = useBreakpoint();
    return () => h("div", { class: "bp" }, `${width.value}:${isMobile.value}`);
  },
});

describe("useBreakpoint", () => {
  beforeEach(() => {
    window.innerWidth = 1280;
  });

  it("默认桌面宽度判定为非移动", () => {
    const w = mount(Probe);
    expect(w.text()).toContain("false");
  });

  it("窄屏 resize 后翻转为移动端", async () => {
    const w = mount(Probe);
    window.innerWidth = 600;
    window.dispatchEvent(new Event("resize"));
    await w.vm.$nextTick();
    expect(w.text()).toContain("true");
  });

  it("暴露断点常量 960", () => {
    expect(MOBILE_BREAKPOINT).toBe(960);
  });
});
