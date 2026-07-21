// AttachmentManager 单测（守护 #10：附件缩略图走部门隔离预签名直连）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AttachmentManager from "@/components/AttachmentManager.vue";

// 仅替换 ElMessage，保留 el-upload/el-button/el-empty 等真实组件
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});
vi.mock("@/api/attachment", () => ({
  fetchAttachments: vi.fn(),
  uploadAttachments: vi.fn(),
  deleteAttachment: vi.fn(),
}));
vi.mock("@/utils/media", () => ({
  resolvePresigned: vi.fn(),
}));

import { fetchAttachments, deleteAttachment } from "@/api/attachment";
import { resolvePresigned } from "@/utils/media";

const imgAtt = {
  id: 1,
  filename: "a.png",
  size: 1024,
  content_type: "image/png",
  media_key: "key/img1",
} as any;
const vidAtt = {
  id: 2,
  filename: "b.mp4",
  size: 2048,
  content_type: "video/mp4",
  media_key: "key/vid1",
} as any;

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(resolvePresigned).mockImplementation(async (keys: string[]) =>
    Object.fromEntries(keys.map((k) => [k, `https://minio/${k}`])),
  );
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("components/AttachmentManager.vue (#10 presigned)", () => {
  it("加载附件后按 media_key 解析预签名并渲染图片/视频缩略图", async () => {
    vi.mocked(fetchAttachments).mockResolvedValue([imgAtt, vidAtt]);
    wrapper = mount(AttachmentManager, {
      props: { entityType: "alarm", entityId: 1 },
    });
    await flushPromises();

    const img = wrapper.find("img.att-thumb");
    const vid = wrapper.find("video.att-thumb");
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("https://minio/key/img1");
    expect(vid.exists()).toBe(true);
    expect(vid.attributes("src")).toBe("https://minio/key/vid1");
  });

  it("预签名为空时降级为文件占位（不渲染 <img>/<video>）", async () => {
    vi.mocked(fetchAttachments).mockResolvedValue([imgAtt]);
    vi.mocked(resolvePresigned).mockResolvedValue({ "key/img1": "" });
    wrapper = mount(AttachmentManager, {
      props: { entityType: "alarm", entityId: 1 },
    });
    await flushPromises();

    expect(wrapper.find("img.att-thumb").exists()).toBe(false);
    expect(wrapper.find("video.att-thumb").exists()).toBe(false);
    expect(wrapper.find(".att-file").text()).toContain("文件");
  });

  it("entityId 为空时不拉取、显示空态", async () => {
    wrapper = mount(AttachmentManager, {
      props: { entityType: "alarm", entityId: null },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("暂无附件");
    expect(vi.mocked(fetchAttachments)).not.toHaveBeenCalled();
  });

  it("点击删除调用 deleteAttachment 并就地移除", async () => {
    vi.mocked(fetchAttachments).mockResolvedValue([imgAtt, vidAtt]);
    vi.mocked(deleteAttachment).mockResolvedValue(undefined);
    wrapper = mount(AttachmentManager, {
      props: { entityType: "alarm", entityId: 1 },
    });
    await flushPromises();

    await wrapper.findAll(".att-del")[0].trigger("click");
    await flushPromises();
    expect(vi.mocked(deleteAttachment)).toHaveBeenCalledWith(1);
  });
});
