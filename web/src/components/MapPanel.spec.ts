import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import MapPanel from "@/components/MapPanel.vue";
import type { MapDevice, MapFence } from "@/types";

const devices: MapDevice[] = [
  { device_no: "LOC-001", name: "定位器A", device_type: "locate", lng: 116.39, lat: 39.91, status: "online", live: true },
  { device_no: "AI-001", name: "防侵B", device_type: "anti_intrusion", lng: 116.4, lat: 39.92, status: "online", live: false },
  { device_no: "TA-001", name: "列车C", device_type: "train_approach", lng: 116.41, lat: 39.9, status: "offline", live: false },
];
const fences: MapFence[] = [
  {
    id: 1,
    name: "施工围栏",
    geometry_wkt: "POLYGON((116.38 39.90, 116.42 39.90, 116.42 39.93, 116.38 39.93, 116.38 39.90))",
  },
];

describe("MapPanel 模拟地图（高清化）", () => {
  it("渲染围栏/设备/比例尺/指北针，且实时设备带脉冲环", () => {
    const wrapper = mount(MapPanel, { props: { devices, fences, height: "320px" } });
    expect(wrapper.find("svg.mock-svg").exists()).toBe(true);
    // 每个围栏渲染一道填充 polygon（fence-poly）；另含底图绿地/湖泊 polygon
    expect(wrapper.findAll(".fence-poly").length).toBe(fences.length);
    expect(wrapper.findAll(".park-fill").length).toBe(2);
    expect(wrapper.find(".lake-fill").exists()).toBe(true);
    // 底图路网/铁路/图例层存在
    expect(wrapper.findAll(".road-casing").length).toBeGreaterThan(0);
    expect(wrapper.find(".rail-core").exists()).toBe(true);
    expect(wrapper.find(".legend").exists()).toBe(true);
    // 每个设备一个主标记圆（dev-core）
    expect(wrapper.findAll(".dev-core").length).toBe(devices.length);
    // 实时设备（LOC-001）应有绿色脉冲环
    expect(wrapper.find(".dev-halo").exists()).toBe(true);
    // 比例尺 + 指北针
    expect(wrapper.find(".scale-bar").exists()).toBe(true);
    expect(wrapper.find(".compass").exists()).toBe(true);
    // 测距/高德相关仅在需要时渲染：默认无 measure 折线、无 moving-core
    expect(wrapper.find(".moving-core").exists()).toBe(false);
  });

  it("setTrajectory / setMovingMarker / removeMovingMarker 联动", async () => {
    const wrapper = mount(MapPanel, { props: { devices, fences } });
    const vm = wrapper.vm as any;
    vm.setTrajectory([
      [116.39, 39.91],
      [116.405, 39.915],
      [116.42, 39.92],
    ]);
    await wrapper.vm.$nextTick();
    // 轨迹含「光晕 + 主描边」两道 polyline
    expect(wrapper.findAll("polyline").length).toBeGreaterThanOrEqual(2);

    vm.setMovingMarker([116.42, 39.92]);
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".moving-core").exists()).toBe(true);

    vm.removeMovingMarker();
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".moving-core").exists()).toBe(false);
  });
});
