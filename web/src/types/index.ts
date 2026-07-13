// 全局类型定义（与后端 ApiResponse 对齐）

// 后端统一响应结构 {code, message, data}
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

// 登录令牌响应
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// 用户信息（对应后端 UserOut）
export interface UserInfo {
  id: number;
  username: string;
  nickname: string | null;
  email: string | null;
  phone: string | null;
  avatar: string | null;
  dept_id: number | null;
  status: boolean;
  is_superuser: boolean;
  role_codes: string[];
  permission_codes: string[];
}

// 登录请求
export interface LoginRequest {
  username: string;
  password: string;
  captcha?: string;
  captcha_key?: string;
}
