// 统一表格分页组件单测：每页条数候选、切换即刷新、重复事件拦截、已选条数展示
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TablePager from "@/components/TablePager.vue";

function mountPager(props: Record<string, unknown> = {}) {
  return mount(TablePager, {
    props: { page: 1, size: 20, total: 135, ...props },
  });
}

function pagination(wrapper: ReturnType<typeof mountPager>) {
  return wrapper.findComponent({ name: "ElPagination" });
}

describe("TablePager", () => {
  it("默认每页条数候选包含 10/20/30/50/100", () => {
    const wrapper = mountPager();
    expect(pagination(wrapper).props("pageSizes")).toEqual([10, 20, 30, 50, 100]);
  });

  it("布局含总数、每页条数下拉与跳转", () => {
    const wrapper = mountPager();
    const layout = String(pagination(wrapper).props("layout"));
    expect(layout).toContain("total");
    expect(layout).toContain("sizes");
    expect(layout).toContain("jumper");
  });

  it("切换每页条数：重置到第 1 页并立即触发刷新", async () => {
    const wrapper = mountPager({ page: 3, size: 20 });
    await pagination(wrapper).vm.$emit("size-change", 50);

    expect(wrapper.emitted("update:size")).toEqual([[50]]);
    expect(wrapper.emitted("update:page")).toEqual([[1]]);
    expect(wrapper.emitted("change")).toHaveLength(1);
  });

  it("每页条数未变化时不触发刷新", async () => {
    const wrapper = mountPager({ size: 20 });
    await pagination(wrapper).vm.$emit("size-change", 20);
    expect(wrapper.emitted("change")).toBeUndefined();
  });

  it("切换页码触发刷新", async () => {
    const wrapper = mountPager({ page: 1 });
    await pagination(wrapper).vm.$emit("current-change", 4);

    expect(wrapper.emitted("update:page")).toEqual([[4]]);
    expect(wrapper.emitted("change")).toHaveLength(1);
  });

  it("页码未变化时拦截重复请求（避免切换条数后被补发的 current-change 二次加载）", async () => {
    const wrapper = mountPager({ page: 1 });
    await pagination(wrapper).vm.$emit("current-change", 1);
    expect(wrapper.emitted("change")).toBeUndefined();
  });

  it("多选时展示已选条数，未选中时不展示", async () => {
    const none = mountPager({ selected: 0 });
    expect(none.find(".table-pager__selected").exists()).toBe(false);

    const some = mountPager({ selected: 7 });
    expect(some.find(".table-pager__selected").text()).toContain("已选");
    expect(some.find(".table-pager__selected").text()).toContain("7");
  });
});
