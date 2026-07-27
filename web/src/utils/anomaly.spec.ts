import { describe, expect, it } from "vitest";
import { collectAnomalies, detectAnomalies } from "./anomaly";

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

describe("collectAnomalies (多序列聚合)", () => {
  it("聚合多条序列并仅保留异常点，按 |z| 降序", () => {
    const series = [
      {
        key: "alarm",
        label: "告警量",
        values: [10, 10, 10, 10, 10, 10, 10, 50],
        periods: ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"],
      },
      {
        key: "device",
        label: "设备活跃",
        // 平稳序列无异常
        values: [5, 5, 5, 5, 5, 5, 5, 5],
        periods: ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"],
      },
    ];
    const items = collectAnomalies(series);
    // 仅告警量尾部 spike 命中
    expect(items).toHaveLength(1);
    expect(items[0].key).toBe("alarm");
    expect(items[0].label).toBe("告警量");
    expect(items[0].period).toBe("d8");
    expect(items[0].direction).toBe("spike");
  });

  it("异常点方向正确（突升/突降分别归类）", () => {
    const series = [
      {
        key: "a",
        label: "A",
        values: [10, 10, 10, 10, 10, 10, 10, 50],
        periods: ["1", "2", "3", "4", "5", "6", "7", "8"],
      },
      {
        key: "b",
        label: "B",
        values: [10, 10, 10, 10, 10, 10, 10, 0],
        periods: ["1", "2", "3", "4", "5", "6", "7", "8"],
      },
    ];
    const items = collectAnomalies(series);
    expect(items).toHaveLength(2);
    const dirs = items.map((x) => x.direction).sort();
    expect(dirs).toEqual(["drop", "spike"]);
  });
});
