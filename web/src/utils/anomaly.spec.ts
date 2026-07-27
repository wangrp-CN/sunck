import { describe, expect, it } from "vitest";
import { detectAnomalies } from "./anomaly";

describe("detectAnomalies (统计基线法)", () => {
  it("序列过短整条不判异常", () => {
    const r = detectAnomalies([1, 2, 3]);
    expect(r).toHaveLength(3);
    expect(r.every((x) => !x.isAnomaly)).toBe(true);
  });

  it("平稳序列无异常", () => {
    const vals = [10, 11, 9, 10, 11, 9, 10, 11, 9, 10];
    const r = detectAnomalies(vals);
    expect(r.every((x) => !x.isAnomaly)).toBe(true);
  });

  it("尾部突增被标记为 spike", () => {
    // 前 7 个平稳，第 8 个暴涨
    const vals = [10, 10, 10, 10, 10, 10, 10, 50];
    const r = detectAnomalies(vals);
    expect(r[7].isAnomaly).toBe(true);
    expect(r[7].direction).toBe("spike");
    expect(r[7].z).toBeGreaterThan(2);
  });

  it("尾部突降被标记为 drop", () => {
    const vals = [10, 10, 10, 10, 10, 10, 10, 0];
    const r = detectAnomalies(vals);
    expect(r[7].isAnomaly).toBe(true);
    expect(r[7].direction).toBe("drop");
    expect(r[7].z).toBeLessThan(-2);
  });

  it("历史样本不足时不误报", () => {
    // 仅 5 点，第 0~2 点历史 < minTrailing，不应判异常
    const vals = [5, 5, 5, 5, 100];
    const r = detectAnomalies(vals);
    expect(r[0].isAnomaly).toBe(false);
    expect(r[1].isAnomaly).toBe(false);
    expect(r[2].isAnomaly).toBe(false);
    // 第 4 点历史 4 个平稳点，100 远超基线 → spike
    expect(r[4].isAnomaly).toBe(true);
  });

  it("k 阈值可调", () => {
    const vals = [10, 12, 8, 11, 9, 10, 11, 12];
    const last = (o: ReturnType<typeof detectAnomalies>) => o[o.length - 1];
    // 默认 k=2.0 不报（12 偏离约 1.5σ），k=1.0 应报
    expect(last(detectAnomalies(vals)).isAnomaly).toBe(false);
    expect(last(detectAnomalies(vals, { k: 1.0 })).isAnomaly).toBe(true);
  });
});
