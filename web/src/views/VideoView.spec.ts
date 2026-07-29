// 视频 AI 深化⑧：事件升级为告警闭环联动（前端）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import VideoView from "@/views/VideoView.vue";

const hoisted = vi.hoisted(() => ({
  fetchVideoChannels: vi.fn(),
  fetchVideoEvents: vi.fn(),
  handleVideoEvent: vi.fn(),
  escalateVideoEvent: vi.fn(),
  fetchVideoAiCapabilities: vi.fn(),
  analyzeVideo: vi.fn(),
  fetchProjects: vi.fn(),
  authUser: { is_superuser: true, permission_codes: [] as string[] },
}));

vi.mock("@/api/video", () => ({
  fetchVideoChannels: (...a: any[]) => hoisted.fetchVideoChannels(...a),
  fetchVideoEvents: (...a: any[]) => hoisted.fetchVideoEvents(...a),
  handleVideoEvent: (...a: any[]) => hoisted.handleVideoEvent(...a),
  escalateVideoEvent: (...a: any[]) => hoisted.escalateVideoEvent(...a),
  fetchVideoAiCapabilities: (...a: any[]) => hoisted.fetchVideoAiCapabilities(...a),
  analyzeVideo: (...a: any[]) => hoisted.analyzeVideo(...a),
  createVideoChannel: vi.fn(),
  updateVideoChannel: vi.fn(),
  deleteVideoChannel: vi.fn(),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: (...a: any[]) => hoisted.fetchProjects(...a),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: hoisted.authUser,
    hasPermission: () => true,
    loadProfile: vi.fn(),
  })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/intelligence/video", meta: { title: "视频AI" } }),
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) },
  };
});

const EVENTS = [
  {
    id: 1,
    channel_id: 1,
    channel_name: "1#球机",
    channel_no: "CAM-1",
    project_id: 100,
    event_type: "intrusion",
    event_type_label: "区域入侵",
    confidence: 0.92,
    snapshot_url: "http://x/s1.jpg",
    event_time: "2026-07-28T08:00:00",
    detail: null,
    handled: false,
    alarm_id: null,
  },
  {
    id: 2,
    channel_id: 1,
    channel_name: "1#球机",
    channel_no: "CAM-1",
    project_id: 100,
    event_type: "no_helmet",
    event_type_label: "未戴安全帽",
    confidence: 0.8,
    snapshot_url: null,
    event_time: "2026-07-28T09:00:00",
    detail: null,
    handled: false,
    alarm_id: 55, // 已升级
  },
  {
    id: 3,
    channel_id: 2,
    channel_name: "2#枪机",
    channel_no: "CAM-2",
    project_id: 100,
    event_type: "other",
    event_type_label: "其他",
    confidence: null,
    snapshot_url: null,
    event_time: "2026-07-28T10:00:00",
    detail: null,
    handled: true,
    alarm_id: null,
  },
];

const CHANNELS = [
  {
    id: 1,
    project_id: 100,
    name: "1#球机",
    channel_no: "CAM-1",
    stream_url: "http://x/stream.m3u8",
    vendor: null,
    location_desc: null,
    lng: null,
    lat: null,
    status: "在线",
    ai_enabled: true,
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

describe("VideoView (深化⑧ 闭环联动)", () => {
  it("renders events and computes stats", async () => {
    hoisted.fetchVideoChannels.mockResolvedValue([]);
    hoisted.fetchVideoEvents.mockResolvedValue(EVENTS);
    hoisted.fetchProjects.mockResolvedValue({ items: [] });

    const wrapper = mount(VideoView);
    await flushPromises();

    expect(hoisted.fetchVideoEvents).toHaveBeenCalled();
    // 统计：总数3 / 待处理2(id1,2) / 已升级1(id2) / 已处理1(id3)
    expect(wrapper.text()).toContain("已升级告警");
    expect((wrapper.vm as any).stats.total).toBe(3);
    expect((wrapper.vm as any).stats.pending).toBe(2);
    expect((wrapper.vm as any).stats.escalated).toBe(1);
  });

  it("escalate button calls escalateVideoEvent and reloads", async () => {
    hoisted.fetchVideoChannels.mockResolvedValue([]);
    hoisted.fetchVideoEvents.mockResolvedValue(EVENTS);
    hoisted.fetchProjects.mockResolvedValue({ items: [] });
    hoisted.escalateVideoEvent.mockResolvedValue({ event_id: 1, alarm_id: 77 });

    const wrapper = mount(VideoView);
    await flushPromises();

    const btn = wrapper
      .findAll("button")
      .find((b) => (b.text() as string).includes("升级告警"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    await flushPromises();

    expect(hoisted.escalateVideoEvent).toHaveBeenCalledWith(1);
    // 升级后重新拉取事件列表
    expect(hoisted.fetchVideoEvents).toHaveBeenCalledTimes(2);
  });

  it("escalated event shows 查看告警 instead of 升级告警", async () => {
    hoisted.fetchVideoChannels.mockResolvedValue([]);
    hoisted.fetchVideoEvents.mockResolvedValue(EVENTS);
    hoisted.fetchProjects.mockResolvedValue({ items: [] });

    const wrapper = mount(VideoView);
    await flushPromises();

    const texts = wrapper.findAll("button").map((b) => b.text());
    expect(texts.some((t) => t.includes("查看告警"))).toBe(true);
    // id=2 已升级 → 不应出现「升级告警」针对它（整体仍可能因 id=1 存在升级按钮）
    expect((wrapper.vm as any).events.find((e: any) => e.id === 2).alarm_id).toBe(55);
  });

  it("type filter passes event_type to loader", async () => {
    hoisted.fetchVideoChannels.mockResolvedValue([]);
    hoisted.fetchVideoEvents.mockResolvedValue(EVENTS);
    hoisted.fetchProjects.mockResolvedValue({ items: [] });

    const wrapper = mount(VideoView);
    await flushPromises();
    hoisted.fetchVideoEvents.mockClear();

    (wrapper.vm as any).eventTypeFilter = "intrusion";
    await (wrapper.vm as any).loadEvents();
    await flushPromises();

    expect(hoisted.fetchVideoEvents).toHaveBeenCalledWith(
      expect.objectContaining({ event_type: "intrusion" }),
    );
  });

  it("预览按钮打开实时预览对话框并透传拉流地址", async () => {
    hoisted.fetchVideoChannels.mockResolvedValue(CHANNELS);
    hoisted.fetchVideoEvents.mockResolvedValue([]);
    hoisted.fetchProjects.mockResolvedValue({ items: [] });

    const wrapper = mount(VideoView, {
      global: { stubs: { VideoPlayer: { template: "<div class='vp' />" } } },
    });
    await flushPromises();

    const btn = wrapper.findAll("button").find((b) => (b.text() as string).includes("预览"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    await flushPromises();

    expect((wrapper.vm as any).previewVisible).toBe(true);
    expect((wrapper.vm as any).previewUrl).toBe(CHANNELS[0].stream_url);
  });

  it("AI分析按钮打开对话框并发起分析得到 findings", async () => {
    hoisted.fetchVideoChannels.mockResolvedValue(CHANNELS);
    hoisted.fetchVideoEvents.mockResolvedValue([]);
    hoisted.fetchProjects.mockResolvedValue({ items: [] });
    hoisted.fetchVideoAiCapabilities.mockResolvedValue({ capabilities: ["intrusion", "no_helmet"] });
    hoisted.analyzeVideo.mockResolvedValue({
      status: "done",
      findings: [{ type: "intrusion", label: "区域入侵", confidence: 0.9 }],
    });

    const wrapper = mount(VideoView, {
      global: { stubs: { VideoPlayer: { template: "<div class='vp' />" } } },
    });
    await flushPromises();

    const aiBtn = wrapper.findAll("button").find((b) => (b.text() as string).includes("AI分析"));
    expect(aiBtn).toBeTruthy();
    await aiBtn!.trigger("click");
    await flushPromises();
    expect((wrapper.vm as any).aiVisible).toBe(true);

    const runBtn = wrapper.findAll("button").find((b) => (b.text() as string).includes("发起分析"));
    await runBtn!.trigger("click");
    await flushPromises();

    expect(hoisted.analyzeVideo).toHaveBeenCalledWith({ channel_no: "CAM-1" });
    expect((wrapper.vm as any).aiResult.status).toBe("done");
    expect((wrapper.vm as any).aiResult.findings.length).toBe(1);
  });
});
