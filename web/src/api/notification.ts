// 通知中心 API 封装（站内信：列表 / 未读计数 / 标记已读 / 全部已读）
import { http } from "@/utils/request";

export type NotificationChannel = "in_app" | "sms" | "voice";
export type NotificationCategory = "alarm" | "hazard" | "system" | "other";

export interface NotificationItem {
  id: number;
  user_id: number;
  channel: NotificationChannel;
  category: NotificationCategory;
  title: string;
  content: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string | null;
}

export interface NotificationPage {
  total: number;
  unread: number;
  items: NotificationItem[];
  page: number;
  size: number;
}

export interface NotificationListParams {
  page?: number;
  size?: number;
  unread_only?: boolean;
}

export function fetchNotifications(params: NotificationListParams = {}): Promise<NotificationPage> {
  return http<NotificationPage>({
    url: "/v1/notifications",
    method: "GET",
    params,
  });
}

export function fetchUnreadCount(): Promise<{ count: number }> {
  return http<{ count: number }>({
    url: "/v1/notifications/unread-count",
    method: "GET",
  });
}

export function markNotificationRead(id: number): Promise<{ id: number; is_read: boolean }> {
  return http<{ id: number; is_read: boolean }>({
    url: `/v1/notifications/${id}/read`,
    method: "POST",
  });
}

export function markAllNotificationsRead(): Promise<{ updated: number }> {
  return http<{ updated: number }>({
    url: "/v1/notifications/read-all",
    method: "POST",
  });
}
