import { defineStore } from "pinia";
import { ref } from "vue";
import { fetchMe, login as apiLogin, logout as apiLogout } from "@/api/auth";
import { clearToken, getToken, setToken } from "@/utils/request";
import type { LoginRequest, UserInfo } from "@/types";

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(getToken());
  const user = ref<UserInfo | null>(null);

  // 是否已登录
  const isLoggedIn = () => Boolean(token.value);

  // 是否拥有某权限
  const hasPermission = (code: string): boolean => {
    if (user.value?.is_superuser) return true;
    return user.value?.permission_codes.includes(code) ?? false;
  };

  // 登录
  async function login(data: LoginRequest): Promise<void> {
    const resp = await apiLogin(data);
    token.value = resp.access_token;
    setToken(resp.access_token);
    // 拉取用户信息失败不应阻断登录态建立与跳转；
    // DashboardView.onMounted 会在 user 为空时兜底重新加载。
    try {
      await loadProfile();
    } catch {
      // 拦截器已统一提示，此处吞掉避免阻断导航
    }
  }

  // 拉取当前用户信息（登录后或刷新页面时调用）
  async function loadProfile(): Promise<void> {
    user.value = await fetchMe();
  }

  // 登出
  async function logout(): Promise<void> {
    try {
      await apiLogout();
    } finally {
      token.value = null;
      user.value = null;
      clearToken();
    }
  }

  return { token, user, isLoggedIn, hasPermission, login, loadProfile, logout };
});
