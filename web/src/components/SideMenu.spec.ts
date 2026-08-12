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
const subStub = {
  template: "<div class='el-sub-menu'><slot name='title' /><slot /></div>",
};

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
    // ① 分组标签已与后端 Permission 模块名对齐
    expect(text).toContain("大屏");
    expect(text).toContain("视频AI");
    expect(text).toContain("告警管理");
    // 作业计划 / 电子围栏 / 人员机械管理(分组) / 人员列表(子菜单) / 机械管理 均为对齐后的分组名
    expect(text).toContain("作业计划");
    expect(text).toContain("电子围栏");
    expect(text).toContain("电子围栏列表");
    expect(text).toContain("人员机械管理");
    expect(text).toContain("人员列表");
    expect(text).toContain("机械管理");
    // 设备管理目录下的三类设备清单
    expect(text).toContain("设备管理");
    expect(text).toContain("人机定位设备列表");
    expect(text).toContain("大机防侵限设备列表");
  });

  it("大机防侵限设备列表菜单指向 /devices/anti-intrusion", () => {
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
    const hit = wrapper
      .findAllComponents(itemStub)
      .find((c) => c.text().includes("大机防侵限设备列表"));
    expect(hit).toBeTruthy();
    expect(hit!.props("index")).toBe("/devices/anti-intrusion");
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
    await wrapper.findComponent(menuStub).vm.$emit("select");
    expect(wrapper.emitted("navigate")).toBeTruthy();
  });
});
