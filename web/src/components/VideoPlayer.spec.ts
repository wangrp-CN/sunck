// VideoPlayer 测试：HLS/原生/不支持/空地址 四类分支
import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VideoPlayer from "@/components/VideoPlayer.vue";

// jsdom 未实现 media.play，补一个返回 resolved promise 的桩，避免 load() 抛错
beforeEach(() => {
  // @ts-expect-error 测试桩
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("VideoPlayer", () => {
  it("mp4 地址走原生播放并设置 src", async () => {
    const wrapper = mount(VideoPlayer, { props: { url: "http://x/cam.mp4" } });
    await wrapper.vm.$nextTick();
    const video = wrapper.find("video").element as HTMLVideoElement;
    expect(video.src).toContain("cam.mp4");
  });

  it("rtsp 地址标记为浏览器不可播放并提示", async () => {
    const wrapper = mount(VideoPlayer, { props: { url: "rtsp://192.168.1.10/stream" } });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("RTSP/RTMP");
    expect(wrapper.find("video").exists()).toBe(false);
  });

  it("空地址显示暂无拉流地址", async () => {
    const wrapper = mount(VideoPlayer, { props: { url: null } });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("暂无拉流地址");
  });
});
