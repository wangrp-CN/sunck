import axios, {
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { ElMessage } from "element-plus";

const TOKEN_KEY = "rm_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// 统一 API 前缀：开发走 Vite 代理 /api，生产可配置 VITE_API_BASE
const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

const request: AxiosInstance = axios.create({
  baseURL,
  timeout: 15000,
});

// 请求拦截：注入 JWT
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getToken();
    if (token) {
      config.headers.set("Authorization", `Bearer ${token}`);
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// 响应拦截：统一解包 ApiResponse，处理 401/业务错误
request.interceptors.response.use(
  (resp: AxiosResponse) => {
    const body = resp.data;
    // 若后端返回了标准结构且 code != 0，视为业务错误
    if (body && typeof body.code === "number" && body.code !== 0) {
      ElMessage.error(body.message || "请求失败");
      return Promise.reject(new Error(body.message || "business error"));
    }
    return resp;
  },
  (error) => {
    const status = error.response?.status;
    if (status === 401) {
      clearToken();
      ElMessage.error("登录已过期，请重新登录");
      // 动态引入 router，避免与 router 模块形成循环依赖
      void import("@/router").then((m) => {
        const r = m.default;
        if (r.currentRoute.value.name !== "login") {
          r.push({ name: "login" });
        }
      });
    } else if (status === 403) {
      ElMessage.error("无权限访问");
    } else if (status === 423) {
      ElMessage.error("账户已锁定，请稍后再试");
    } else {
      ElMessage.error(error.response?.data?.message || "网络错误");
    }
    return Promise.reject(error);
  },
);

// 通用请求封装：直接返回 data 字段
export async function http<T>(config: Parameters<AxiosInstance["request"]>[0]): Promise<T> {
  const resp = await request.request<ApiResponse<T>>(config);
  return (resp.data as ApiResponse<T>).data;
}

export default request;
