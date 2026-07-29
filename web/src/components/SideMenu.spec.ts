// SideMenu 测试：菜单项内容正确渲染、点击项触发 navigate 事件
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import SideMenu from "@/components/SideMenu.vue";

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/dashboard" }),
  useRouter: () => ({ push: vi.fn() }),
}));

const menuStub = { template: "<div class='el-menu'><slot /></div>" };
const itemStub = {
  template: "<div class='el-menu-item'><slot /></div>",
  props: ["index"],
  emits: ["select"],
};
const subStub = { template: "<div class='el-sub-menu'><slot /></div>" };

describe("SideMenu", () => {
  it("渲染核心导航项", () => {
    const wrapper = mount(SideMenu, {
      global: {
        stubs: {
          "el-icon": { template: "<i><slot /></i>" },
          "el-menu": menuStub,
          "el-menu-item": itemStub,
          "el-sub-menu": subStub,
        },
      },
    });
    const text = wrapper.text();
    expect(text).toContain("监控大屏");
    expect(text).toContain("视频AI");
    expect(text).toContain("告警管理");
  });

  it("点击菜单项 emit navigate（用于移动端关闭抽屉）", async () => {
    const wrapper = mount(SideMenu, {
      global: {
        stubs: {
          "el-icon": { template: "<i><slot /></i>" },
          "el-menu": menuStub,
          "el-menu-item": itemStub,
          "el-sub-menu": subStub,
        },
      },
    });
    // 手动触发 el-menu 的 select 事件（由 SideMenu 监听并转 emit navigate）
    await (wrapper.find(".el-menu").vm as any).$emit("select");
    expect(wrapper.emitted("navigate")).toBeTruthy();
  });
});
