// request 拦截器测试：
// - silent=true 的请求失败（如媒体 404）不弹全局 ElMessage 错误提示
// - 非 silent 请求失败仍弹提示
// - 401 即使 silent 也提示并清理登录态（登录态失效不可静默）
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

import { ElMessage } from "element-plus";
import request, { http } from "@/utils/request";

// 安装桩 adapter：按状态码抛 AxiosError（走响应错误拦截器）
function installErrorAdapter(status: number, message: string) {
  request.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const response = {
      data: { code: status, message, data: null },
      status,
      statusText: "ERR",
      headers: {},
      config,
    };
    throw new AxiosError(
      `Request failed with status code ${status}`,
      "ERR_BAD_REQUEST",
      config,
      null,
      response as never,
    );
  };
}

function installBusinessErrorAdapter(code: number, message: string) {
  request.defaults.adapter = async (config: InternalAxiosRequestConfig) => ({
    data: { code, message, data: null },
    status: 200,
    statusText: "OK",
    headers: {},
    config: { ...config, headers: config.headers ?? new AxiosHeaders() },
  });
}

describe("utils/request silent 静默请求", () => {
  beforeEach(() => {
    vi.mocked(ElMessage.error).mockClear();
    localStorage.clear();
  });

  it("silent=true 时 HTTP 404 不弹全局错误提示", async () => {
    installErrorAdapter(404, "媒体对象不存在或无权访问");
    await expect(
      http({ url: "/v1/media/access", method: "GET", silent: true }),
    ).rejects.toBeTruthy();
    expect(vi.mocked(ElMessage.error)).not.toHaveBeenCalled();
  });

  it("非 silent 请求 HTTP 404 仍弹错误提示", async () => {
    installErrorAdapter(404, "媒体对象不存在或无权访问");
    await expect(http({ url: "/v1/media/access", method: "GET" })).rejects.toBeTruthy();
    expect(vi.mocked(ElMessage.error)).toHaveBeenCalledWith("媒体对象不存在或无权访问");
  });

  it("401 即使 silent 也提示并清理 token（登录态失效不可静默）", async () => {
    localStorage.setItem("rm_token", "t");
    installErrorAdapter(401, "unauthorized");
    await expect(
      http({ url: "/v1/anything", method: "GET", silent: true }),
    ).rejects.toBeTruthy();
    expect(vi.mocked(ElMessage.error)).toHaveBeenCalledWith("登录已过期，请重新登录");
    expect(localStorage.getItem("rm_token")).toBeNull();
  });

  it("silent=true 时业务错误（HTTP200 code!=0）也不弹提示", async () => {
    installBusinessErrorAdapter(400, "业务失败");
    await expect(
      http({ url: "/v1/x", method: "GET", silent: true }),
    ).rejects.toBeTruthy();
    expect(vi.mocked(ElMessage.error)).not.toHaveBeenCalled();
  });
});
