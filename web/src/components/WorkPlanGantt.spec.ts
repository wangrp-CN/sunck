import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import WorkPlanGantt from "@/components/WorkPlanGantt.vue";
import type { WorkPlan } from "@/types";

const fixtures: WorkPlan[] = [
  {
    id: 1,
    project_id: 1,
    name: "计划A-年初施工",
    is_start: false,
    status: "草稿",
    active: false,
    plan_start: "2026-01-01",
    plan_end: "2026-03-31",
    devices: [{ device_type: "loc", device_no: "L1" }, { device_type: "ai", device_no: "A1" }],
  },
  {
    id: 2,
    project_id: 1,
    name: "计划B-春季监护",
    is_start: true,
    status: "执行中",
    active: true,
    plan_start: "2026-02-15",
    plan_end: "2026-05-15",
    devices: [{ device_type: "ta", device_no: "T1" }],
  },
  {
    id: 3,
    project_id: 2,
    name: "计划C-全年巡检",
    is_start: false,
    status: "已完成",
    active: false,
    plan_start: "2026-04-01",
    plan_end: "2026-12-31",
    devices: [],
  },
];

describe("WorkPlanGantt", () => {
  it("按计划数渲染行与横条", () => {
    const wrapper = mount(WorkPlanGantt, { props: { plans: fixtures } });
    expect(wrapper.findAll(".gantt-row").length).toBe(3);
    expect(wrapper.findAll(".gantt-bar").length).toBe(3);
  });

  it("横条按 active/状态分色，并显示绑定设备数", () => {
    const wrapper = mount(WorkPlanGantt, { props: { plans: fixtures } });
    const bars = wrapper.findAll(".gantt-bar");
    // rows 按 start 升序：A(草稿) / B(监控中) / C(已完成)
    expect(bars[0].classes()).toContain("st-draft");
    expect(bars[1].classes()).toContain("is-active");
    expect(bars[2].classes()).toContain("st-done");
    // 设备数徽标
    expect(bars[0].text()).toContain("设2");
    expect(bars[1].text()).toContain("设1");
  });

  it("横条位置由时间窗映射（最早计划靠左、宽度为正）", () => {
    const wrapper = mount(WorkPlanGantt, { props: { plans: fixtures } });
    const first = wrapper.find(".gantt-bar");
    const style = first.attributes("style") || "";
    expect(style).toMatch(/left:\s*[\d.]+%/);
    expect(style).toMatch(/width:\s*[\d.]+%/);
    // 最早开始的计划应贴近左端（<20%）
    const left = parseFloat((style.match(/left:\s*([\d.]+)%/) || [])[1] || "100");
    expect(left).toBeLessThan(20);
  });

  it("点击计划条 emit select 携带对应计划", async () => {
    const wrapper = mount(WorkPlanGantt, { props: { plans: fixtures } });
    await wrapper.findAll(".gantt-row")[0].trigger("click");
    const ev = wrapper.emitted("select");
    expect(ev).toBeTruthy();
    expect((ev![0][0] as WorkPlan).id).toBe(1);
  });

  it("无带时间窗的计划时显示空态", () => {
    const wrapper = mount(WorkPlanGantt, {
      props: { plans: [{ id: 9, project_id: null, name: "无时间", is_start: false, status: "草稿" }] },
    });
    expect(wrapper.find(".gantt").exists()).toBe(false);
    expect(wrapper.find(".gantt-empty").exists()).toBe(true);
  });
});
