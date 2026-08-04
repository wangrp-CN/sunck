// 统一批量操作工具条单测：已选条数文案、禁用态、事件、权限开关、插槽
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BatchActions from "@/components/BatchActions.vue";

function mountBar(props: Record<string, unknown> = {}, slots: Record<string, string> = {}) {
  return mount(BatchActions, { props: { selected: 0, ...props }, slots });
}

function deleteBtn(wrapper: ReturnType<typeof mountBar>) {
  return wrapper.find(".batch-actions__delete");
}

describe("BatchActions", () => {
  it("实时展示「已选择 N 项」", () => {
    expect(mountBar({ selected: 0 }).find(".batch-actions__count").text()).toContain("已选择");
    expect(mountBar({ selected: 5 }).find(".batch-actions__count").text()).toContain("5");
  });

  it("未选中时批量删除与清空选择均禁用", () => {
    const wrapper = mountBar({ selected: 0 });
    expect(deleteBtn(wrapper).attributes("disabled")).toBeDefined();
    expect(wrapper.find(".batch-actions__clear").attributes("disabled")).toBeDefined();
  });

  it("有选中项时按钮可用并触发 batch-delete / clear", async () => {
    const wrapper = mountBar({ selected: 3 });
    expect(deleteBtn(wrapper).attributes("disabled")).toBeUndefined();

    await deleteBtn(wrapper).trigger("click");
    await wrapper.find(".batch-actions__clear").trigger("click");

    expect(wrapper.emitted("batch-delete")).toHaveLength(1);
    expect(wrapper.emitted("clear")).toHaveLength(1);
  });

  it("showDelete=false 时隐藏批量删除按钮（无删除权限）", () => {
    const wrapper = mountBar({ selected: 2, showDelete: false });
    expect(deleteBtn(wrapper).exists()).toBe(false);
  });

  it("支持自定义文案与默认插槽扩展批量动作", () => {
    const wrapper = mountBar(
      { selected: 1, deleteText: "批量作废" },
      { default: '<button class="extra-action">批量处置</button>' },
    );
    expect(deleteBtn(wrapper).text()).toBe("批量作废");
    expect(wrapper.find(".extra-action").exists()).toBe(true);
  });
});
