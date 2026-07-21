// MediaUpload 单测（守护 #10：上传媒体走部门隔离预签名直连）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MediaUpload from "@/components/MediaUpload.vue";

// 仅替换 ElMessage，保留 el-button/el-input 等真实组件
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});
vi.mock("@/api/media", () => ({ uploadMedia: vi.fn() }));
// 保留真实的 mediaKeyFromUrl，仅桩 resolvePresigned，以验证 key 提取链路
vi.mock("@/utils/media", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, resolvePresigned: vi.fn() };
});

import { resolvePresigned } from "@/utils/media";

// resolvePresigned 回显签名结果，便于断言 mediaKeyFromUrl 提取出的 key 正确
function echoResolve() {
  vi.mocked(resolvePresigned).mockImplementation(async (keys: string[]) =>
    Object.fromEntries(keys.map((k) => [k, `SIGNED:${k}`])),
  );
}

const imgUrl = "https://host/api/v1/media/abc.jpg?sig=1";
const vidUrl = "https://host/api/v1/media/def.mp4?sig=2";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  echoResolve();
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("components/MediaUpload.vue (#10 presigned)", () => {
  it("按类型渲染图片/视频，且 src 为经 key 提取后的预签名直连", async () => {
    wrapper = mount(MediaUpload, { props: { modelValue: [imgUrl, vidUrl] } });
    await flushPromises();

    const img = wrapper.find("img.thumb");
    const vid = wrapper.find("video.thumb");
    expect(img.exists()).toBe(true);
    // mediaKeyFromUrl(imgUrl) = "abc.jpg" → resolvePresigned 回显 SIGNED:abc.jpg
    expect(img.attributes("src")).toBe("SIGNED:abc.jpg");
    expect(vid.exists()).toBe(true);
    expect(vid.attributes("src")).toBe("SIGNED:def.mp4");
  });

  it("预签名为空时降级为文件占位", async () => {
    vi.mocked(resolvePresigned).mockResolvedValue({ "abc.jpg": "" });
    wrapper = mount(MediaUpload, { props: { modelValue: [imgUrl] } });
    await flushPromises();

    expect(wrapper.find("img.thumb").exists()).toBe(false);
    expect(wrapper.find(".file-box").text()).toContain("文件");
  });

  it("无媒体时显示空态", async () => {
    wrapper = mount(MediaUpload, { props: { modelValue: [] } });
    await flushPromises();
    expect(wrapper.text()).toContain("暂无媒体");
  });
});
