import { http } from "@/utils/request";
import type { LoginRequest, TokenResponse, UserInfo } from "@/types";

// 登录
export function login(data: LoginRequest): Promise<TokenResponse> {
  return http<TokenResponse>({
    url: "/v1/auth/login",
    method: "POST",
    data,
  });
}

// 当前用户信息
export function fetchMe(): Promise<UserInfo> {
  return http<UserInfo>({
    url: "/v1/auth/me",
    method: "GET",
  });
}

// 登出
export function logout(): Promise<null> {
  return http<null>({
    url: "/v1/auth/logout",
    method: "POST",
  });
}
