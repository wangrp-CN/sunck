// 媒体 presigned 工具单测（守护 OPTIMIZATION_REPORT #10 安全特性）
// - mediaKeyFromUrl：从代理 URL / 裸 key 提取后端对象 key
// - resolvePresigned：批量解析为部门隔离预签名直连 URL；单条失败降级空串
import { describe, it, expect, vi } from "vitest";
import { mediaKeyFromUrl, resolvePresigned } from "@/utils/media";

// 只桩掉底层 API，保留真实工具函数逻辑
vi.mock("@/api/media", () => ({
  fetchMediaAccess: vi.fn(),
}));

import { fetchMediaAccess } from "@/api/media";

describe("utils/media.ts (OPTIMIZATION_REPORT #10)", () => {
  describe("mediaKeyFromUrl", () => {
    it("从代理 URL 剥离前缀与 query，得到裸 key", () => {
      expect(mediaKeyFromUrl("/api/v1/media/abc123?x=1")).toBe("abc123");
      expect(mediaKeyFromUrl("http://host/api/v1/media/key1?sig=2")).toBe("key1");
    });

    it("裸 key 与空串原样返回", () => {
      expect(mediaKeyFromUrl("abc123")).toBe("abc123");
      expect(mediaKeyFromUrl("")).toBe("");
    });
  });

  describe("resolvePresigned", () => {
    it("按原始入参为键，映射到对应预签名 URL", async () => {
      vi.mocked(fetchMediaAccess).mockImplementation(async (k: string) => ({
        key: k,
        presigned_url: `https://minio.test/${k}?sign`,
      }));
      const res = await resolvePresigned(["k1", "k2"]);
      expect(res).toEqual({
        k1: "https://minio.test/k1?sign",
        k2: "https://minio.test/k2?sign",
      });
    });

    it("单条失败降级为空串，其余保持有效（前端判空兜底）", async () => {
      vi.mocked(fetchMediaAccess).mockImplementation(async (k: string) => {
        if (k === "bad") throw new Error("403");
        return { key: k, presigned_url: `https://minio.test/${k}` };
      });
      const res = await resolvePresigned(["ok", "bad"]);
      expect(res.ok).toBe("https://minio.test/ok");
      expect(res.bad).toBe("");
    });

    it("空输入返回空对象", async () => {
      const res = await resolvePresigned([]);
      expect(res).toEqual({});
    });
  });
});
