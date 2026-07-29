// 关联热力对比页面单测：双窗渲染、变化摘要（新增/消失/增强减弱）、空态与缺窗校验
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import CorrelationCompareView from "@/views/CorrelationCompareView.vue";

const hoisted = vi.hoisted(() => ({
  getCorrelationCompare: vi.fn(),
  elMessageWarning: vi.fn(),
  elMessageError: vi.fn(),
  authUser: { is_superuser: true, permission_codes: [] as string[] },
}));

vi.mock("@/api/metrics", () => ({
  getCorrelationCompare: (...a: any[]) => hoisted.getCorrelationCompare(...a),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({ user: hoisted.authUser, hasPermission: () => true })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({
    path: "/intelligence/correlation-compare",
    meta: { title: "关联热力对比" },
  }),
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: {
      success: vi.fn(),
      warning: (...a: any[]) => hoisted.elMessageWarning(...a),
      error: (...a: any[]) => hoisted.elMessageError(...a),
      info: vi.fn(),
    },
  };
});

function point(lng: number, lat: number, w: number) {
  return {
    id: 1,
    project_id: 100,
    project_name: "示范项目",
    spatial_type: "geo" as const,
    fence_name: null,
    grid_cell: "3990,11640",
    lng,
    lat,
    gcj02: { lng: lng + 0.01, lat: lat + 0.01 },
    weight: w,
    alarm_count: w,
    device_count: 2,
    max_level: "警告",
    is_cross_device: true,
    root_cause_hint: "x",
  };
}

function makeResp(opts: {
  aPoints?: any[];
  bPoints?: any[];
  newN?: number;
  removedN?: number;
  changedN?: number;
}) {
  const diffItem = (key: string) => ({
    key,
    project_id: 100,
    project_name: "示范项目",
    spatial_type: "geo" as const,
    scope_text: `地理网格 ${key}`,
    fence_name: null,
    grid_cell: "3990,11640",
    weight: 3,
    alarm_count: 3,
    device_count: 2,
    max_level: "警告",
  });
  return {
    window_a: {
      start: "2026-07-01T00:00:00",
      end: "2026-07-08T00:00:00",
      total: (opts.aPoints || []).length,
      cross_device_total: 1,
      alarm_total: 10,
      points: opts.aPoints || [],
    },
    window_b: {
      start: "2026-07-08T00:00:00",
      end: "2026-07-15T00:00:00",
      total: (opts.bPoints || []).length,
      cross_device_total: 1,
      alarm_total: 12,
      points: opts.bPoints || [],
    },
    diff: {
      new: Array.from({ length: opts.newN || 0 }, (_, i) => diffItem(`n${i}`)),
      removed: Array.from({ length: opts.removedN || 0 }, (_, i) => diffItem(`r${i}`)),
      changed: Array.from({ length: opts.changedN || 0 }, (_, i) => ({
        ...diffItem(`c${i}`),
        a_weight: 3,
        b_weight: 5,
        delta: 2,
        a_max_level: "警告",
        b_max_level: "严重",
        a_device_count: 2,
        b_device_count: 2,
      })),
    },
  };
}

afterEach(() => vi.clearAllMocks());

describe("CorrelationCompareView", () => {
  it("renders two windows and the diff summary after load", async () => {
    hoisted.getCorrelationCompare.mockResolvedValue(
      makeResp({
        aPoints: [point(116.4, 39.9, 3)],
        bPoints: [point(116.5, 39.95, 5)],
        newN: 1,
        removedN: 1,
        changedN: 1,
      }),
    );
    const wrapper = mount(CorrelationCompareView);
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("关联热力对比");
    expect(hoisted.getCorrelationCompare).toHaveBeenCalled();
    expect(text).toContain("新增热点");
    expect(text).toContain("消失热点");
    expect(text).toContain("增强");
    expect((wrapper.vm as any).diffTotal).toBe(3);
  });

  it("shows empty-diff state when no change between windows", async () => {
    hoisted.getCorrelationCompare.mockResolvedValue(
      makeResp({ aPoints: [point(1, 1, 1)], bPoints: [point(2, 2, 1)] }),
    );
    const wrapper = mount(CorrelationCompareView);
    await flushPromises();
    expect(wrapper.text()).toContain("无变化");
  });

  it("warns and aborts when both time windows are missing", async () => {
    hoisted.getCorrelationCompare.mockResolvedValue(makeResp({}));
    const wrapper = mount(CorrelationCompareView);
    await flushPromises();

    (wrapper.vm as any).rangeA = null;
    (wrapper.vm as any).rangeB = null;
    await (wrapper.vm as any).load();

    expect(hoisted.elMessageWarning).toHaveBeenCalled();
    // 仅 mount 时自动加载了一次，缺窗后未再次请求
    expect(hoisted.getCorrelationCompare).toHaveBeenCalledTimes(1);
  });
});
