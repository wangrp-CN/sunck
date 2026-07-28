// 阈值自学习页面单测（#④-1 前端配置页）：渲染、超管标定/应用、只读权限降级
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ThresholdAutoLearningView from "@/views/ThresholdAutoLearningView.vue";

const hoisted = vi.hoisted(() => ({
  getThresholdCalibration: vi.fn(),
  calibrateThreshold: vi.fn(),
  applyThreshold: vi.fn(),
  authUser: { is_superuser: true, permission_codes: [] as string[] },
}));

vi.mock("@/api/intelligence", () => ({
  getThresholdCalibration: (...a: any[]) => hoisted.getThresholdCalibration(...a),
  calibrateThreshold: (...a: any[]) => hoisted.calibrateThreshold(...a),
  applyThreshold: (...a: any[]) => hoisted.applyThreshold(...a),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({ user: hoisted.authUser, loadProfile: vi.fn() })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/intelligence/threshold", meta: { title: "阈值自学习" } }),
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

function clickByText(wrapper: any, text: string) {
  const btn = wrapper
    .findAll("button")
    .find((b: any) => (b.text() as string).includes(text));
  if (!btn) throw new Error(`button not found: ${text}`);
  btn.trigger("click");
}

const SAMPLE_RESULT = {
  calibration_id: 7,
  id: 7,
  window_days: 90,
  sample_count: 100,
  target_breach_rate: 0.1,
  current_threshold: 60,
  recommended_threshold: 75,
  method: "quantile",
  min_threshold: 40,
  max_threshold: 90,
  actual_breach_rate: 0.12,
  sweep: [
    { threshold: 40, breach_rate: 0.4 },
    { threshold: 75, breach_rate: 0.1 },
    { threshold: 90, breach_rate: 0.02 },
  ],
  stats: { min: 30, max: 95, mean: 60, median: 58, p75: 70, p90: 82, p95: 90 },
  message: "标定完成",
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("ThresholdAutoLearningView", () => {
  it("renders page title and current active threshold", async () => {
    hoisted.authUser.is_superuser = true;
    hoisted.getThresholdCalibration.mockResolvedValue({
      active_threshold: 60,
      latest: null,
    });
    const wrapper = mount(ThresholdAutoLearningView);
    await flushPromises();
    expect(wrapper.text()).toContain("阈值自学习");
    expect(wrapper.text()).toContain("60");
  });

  it("non-superuser sees read-only tip and disabled calibrate", async () => {
    hoisted.authUser.is_superuser = false;
    hoisted.getThresholdCalibration.mockResolvedValue({
      active_threshold: 60,
      latest: null,
    });
    const wrapper = mount(ThresholdAutoLearningView);
    await flushPromises();
    expect(wrapper.text()).toContain("只读 · 仅超管可标定/应用");
    const calibrateBtn = wrapper
      .findAll("button")
      .find((b: any) => (b.text() as string).includes("运行标定"));
    expect(calibrateBtn?.attributes("disabled")).toBeDefined();
  });

  it("superuser can calibrate then apply recommended threshold", async () => {
    hoisted.authUser.is_superuser = true;
    hoisted.getThresholdCalibration.mockResolvedValue({
      active_threshold: 60,
      latest: null,
    });
    hoisted.calibrateThreshold.mockResolvedValue(SAMPLE_RESULT);
    hoisted.applyThreshold.mockResolvedValue({ active_threshold: 75, source: "auto" });

    const wrapper = mount(ThresholdAutoLearningView);
    await flushPromises();

    clickByText(wrapper, "运行标定");
    await flushPromises();

    expect(hoisted.calibrateThreshold).toHaveBeenCalled();
    expect(wrapper.text()).toContain("应用此阈值");

    clickByText(wrapper, "应用此阈值");
    await flushPromises();

    expect(hoisted.applyThreshold).toHaveBeenCalledWith(
      expect.objectContaining({ threshold: 75, source: "auto" }),
    );
  });

  it("rejects calibrate when min >= max threshold", async () => {
    hoisted.authUser.is_superuser = true;
    hoisted.getThresholdCalibration.mockResolvedValue({
      active_threshold: 60,
      latest: null,
    });
    const wrapper = mount(ThresholdAutoLearningView);
    await flushPromises();

    // 下界 >= 上界，校验应拦截、不调用标定接口
    (wrapper.vm as any).form.min_threshold = 90;
    (wrapper.vm as any).form.max_threshold = 90;
    await flushPromises();

    clickByText(wrapper, "运行标定");
    await flushPromises();

    expect(hoisted.calibrateThreshold).not.toHaveBeenCalled();
  });
});
