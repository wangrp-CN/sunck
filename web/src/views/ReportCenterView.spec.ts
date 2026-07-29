// 报表中心单测：预览渲染（项目风险 + 设备健康）+ 导出调用 + 周期切换重拉
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReportCenterView from "@/views/ReportCenterView.vue";

const PREVIEW = {
  period_type: "weekly",
  period_label: "周报（上周）",
  range_start: "2026-07-20T00:00:00",
  range_end: "2026-07-27T00:00:00",
  summary: {
    project_count: 2,
    avg_risk: 70.5,
    high_risk_count: 1,
    device_count: 3,
    avg_health: 80,
    offline_count: 1,
    health_dist: { 优: 1, 良: 1, 中: 0, 差: 1 },
    online_dist: { fresh: 2, stale: 0, offline: 1 },
  },
  project_rows: [
    { project_id: 1, name: "项目A", risk_index: 80, risk_level: "高", prev_risk_index: 70, delta: 10 },
    { project_id: 2, name: "项目B", risk_index: 50, risk_level: "中", prev_risk_index: null, delta: null },
  ],
  device_rows: [
    { device_no: "D1", name: "设备1", health_score: 55, health_level: "差", online_state: "离线" },
  ],
  top_risky_projects: [],
  top_unhealthy_devices: [
    { device_no: "D1", name: "设备1", health_score: 55, health_level: "差", online_state: "离线" },
  ],
};

const hoisted = vi.hoisted(() => ({
  getRiskHealthReportPreview: vi.fn(),
  exportRiskHealthReport: vi.fn(),
  elSuccess: vi.fn(),
  elError: vi.fn(),
}));

vi.mock("@/api/reports", () => ({
  getRiskHealthReportPreview: (...a: any[]) => hoisted.getRiskHealthReportPreview(...a),
  exportRiskHealthReport: (...a: any[]) => hoisted.exportRiskHealthReport(...a),
}));
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: {
      error: (...a: any[]) => hoisted.elError(...a),
      warning: vi.fn(),
      success: (...a: any[]) => hoisted.elSuccess(...a),
      info: vi.fn(),
    },
  };
});

afterEach(() => {
  hoisted.getRiskHealthReportPreview.mockReset();
  hoisted.exportRiskHealthReport.mockReset();
  hoisted.elSuccess.mockReset();
  hoisted.elError.mockReset();
  // jsdom 未实现 URL.createObjectURL，导出时补桩
  if (typeof URL.createObjectURL !== "function") {
    (URL as any).createObjectURL = () => "blob:x";
    (URL as any).revokeObjectURL = () => {};
  }
});

describe("ReportCenterView", () => {
  it("挂载后加载预览并渲染项目风险 + 设备健康", async () => {
    hoisted.getRiskHealthReportPreview.mockResolvedValue(PREVIEW);
    const wrapper = mount(ReportCenterView);
    await flushPromises();
    expect(hoisted.getRiskHealthReportPreview).toHaveBeenCalledTimes(1);
    expect(hoisted.getRiskHealthReportPreview).toHaveBeenCalledWith({ period_type: "weekly" });
    expect(wrapper.text()).toContain("项目A");
    expect(wrapper.text()).toContain("项目B");
    expect(wrapper.text()).toContain("设备1");
    wrapper.unmount();
  });

  it("点击导出 Excel / PDF 调用导出接口（带 period_type）", async () => {
    hoisted.getRiskHealthReportPreview.mockResolvedValue(PREVIEW);
    hoisted.exportRiskHealthReport.mockResolvedValue(new Blob(["x"]));
    (URL as any).createObjectURL = () => "blob:x";
    (URL as any).revokeObjectURL = () => {};
    const wrapper = mount(ReportCenterView);
    await flushPromises();

    const excelBtn = wrapper.findAll("button").find((b) => b.text().includes("导出 Excel"));
    expect(excelBtn).toBeTruthy();
    await excelBtn!.trigger("click");
    await flushPromises();
    expect(hoisted.exportRiskHealthReport).toHaveBeenCalledWith("excel", { period_type: "weekly" });

    const pdfBtn = wrapper.findAll("button").find((b) => b.text().includes("导出 PDF"));
    await pdfBtn!.trigger("click");
    await flushPromises();
    expect(hoisted.exportRiskHealthReport).toHaveBeenCalledWith("pdf", { period_type: "weekly" });
    wrapper.unmount();
  });

  it("切换周期会重新拉取预览", async () => {
    hoisted.getRiskHealthReportPreview.mockResolvedValue(PREVIEW);
    const wrapper = mount(ReportCenterView);
    await flushPromises();
    expect(hoisted.getRiskHealthReportPreview).toHaveBeenCalledTimes(1);

    const group = wrapper.findComponent({ name: "ElRadioGroup" });
    await group.setValue("daily");
    await flushPromises();
    expect(hoisted.getRiskHealthReportPreview).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
});
