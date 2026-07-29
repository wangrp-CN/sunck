// ResponsiveTable 包装测试：滚动容器 + 透传插槽到内部 el-table
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ResponsiveTable from "@/components/ResponsiveTable.vue";

describe("ResponsiveTable", () => {
  it("渲染滚动容器并把列作为默认插槽透传给 el-table", () => {
    const wrapper = mount(ResponsiveTable, {
      attrs: { border: true, stripe: true },
      slots: { default: "<div class='cell'>A</div>" },
      global: {
        stubs: {
          "el-table": { template: "<div class='el-table'><slot /></div>" },
        },
      },
    });
    expect(wrapper.find(".table-scroll").exists()).toBe(true);
    expect(wrapper.find(".el-table").exists()).toBe(true);
    expect(wrapper.find(".cell").exists()).toBe(true);
  });
});
