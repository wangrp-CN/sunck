// geo 工具：坐标系互转 + 距离量算 + WKT 解析/生成（与后端 app/core/geo.py 算法一致）
import { describe, expect, it } from "vitest";
import {
  fmtDistance,
  gcj02ToWgs84,
  haversineMeters,
  parseWktToGcjPath,
  pointsToWkt,
  wgs84ToGcj02,
} from "@/utils/geo";

describe("haversineMeters", () => {
  it("相同点距离为 0", () => {
    expect(haversineMeters([116.397, 39.908], [116.397, 39.908])).toBeCloseTo(0, 6);
  });

  it("约 1km 距离在合理范围", () => {
    const d = haversineMeters([116.397, 39.908], [116.408, 39.908]);
    // 经度差约 0.011° @ 北纬40°，约 0.94~0.97 km
    expect(d).toBeGreaterThan(900);
    expect(d).toBeLessThan(1000);
  });
});

describe("fmtDistance", () => {
  it("小于 1km 显示米", () => {
    expect(fmtDistance(350.5)).toBe("350.5 m");
  });
  it("大于等于 1km 显示千米", () => {
    expect(fmtDistance(1500)).toBe("1.50 km");
  });
});

describe("parseWktToGcjPath", () => {
  it("解析 POLYGON 首个环为 GCJ-02 路径", () => {
    const path = parseWktToGcjPath("POLYGON((116.4 39.9, 116.41 39.9, 116.41 39.91))");
    expect(path.length).toBe(3);
    // 境内坐标应被偏移（与原始不同）
    expect(path[0][0]).not.toBeCloseTo(116.4, 4);
  });
  it("空/非法返回空数组", () => {
    expect(parseWktToGcjPath("")).toEqual([]);
    expect(parseWktToGcjPath(undefined)).toEqual([]);
    expect(parseWktToGcjPath("LINESTRING EMPTY")).toEqual([]);
  });
});

describe("wgs84ToGcj02 / gcj02ToWgs84 互逆", () => {
  it("在中国境内互相可还原到厘米级", () => {
    const samples: [number, number][] = [
      [116.397, 39.908],
      [121.499, 31.23],
      [113.264, 23.129],
    ];
    for (const [lng, lat] of samples) {
      const [gl, gt] = wgs84ToGcj02(lng, lat);
      const [bl, bt] = gcj02ToWgs84(gl, gt);
      expect(Math.abs(bl - lng)).toBeLessThan(1e-5);
      expect(Math.abs(bt - lat)).toBeLessThan(1e-5);
    }
  });

  it("境外坐标原样返回", () => {
    expect(gcj02ToWgs84(2.352, 48.856)).toEqual([2.352, 48.856]);
    expect(wgs84ToGcj02(2.352, 48.856)).toEqual([2.352, 48.856]);
  });
});

describe("pointsToWkt", () => {
  it("生成闭合 POLYGON 且坐标保留 6 位", () => {
    const wkt = pointsToWkt([
      [116.4, 39.9],
      [116.41, 39.9],
      [116.41, 39.91],
      [116.4, 39.91],
    ]);
    expect(wkt).toBe(
      "POLYGON((116.400000 39.900000, 116.410000 39.900000, 116.410000 39.910000, 116.400000 39.910000, 116.400000 39.900000))",
    );
  });

  it("顶点不足 3 个返回 null", () => {
    expect(pointsToWkt([[1, 2], [3, 4]])).toBeNull();
    expect(pointsToWkt([])).toBeNull();
  });
});
