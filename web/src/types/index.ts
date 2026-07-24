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

// 验证码响应
export interface CaptchaResponse {
  captcha_key: string;
  captcha_image: string;
  expire_seconds: number;
}

// 项目状态
export type ProjectStatus = "在建" | "停工" | "竣工";

// 项目信息（对应后端 ProjectOut）
export interface Project {
  id: number;
  dept_id: number | null;
  name: string;
  short_name: string | null;
  intro: string | null;
  start_date: string | null;
  end_date: string | null;
  duration: number | null;
  mileage: string | null;
  section: string | null;
  coordinate: string | null;
  status: ProjectStatus;
  created_by: number | null;
  created_at: string | null;
}

// 项目分页响应
export interface ProjectPage {
  items: Project[];
  total: number;
  page: number;
  size: number;
}

// 新建项目请求
export interface ProjectCreate {
  name: string;
  dept_id: number;
  short_name?: string | null;
  intro?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  duration?: number | null;
  mileage?: string | null;
  section?: string | null;
  coordinate?: string | null;
  status?: ProjectStatus;
}

// 更新项目请求
export interface ProjectUpdate {
  name?: string;
  dept_id?: number;
  short_name?: string | null;
  intro?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  duration?: number | null;
  mileage?: string | null;
  section?: string | null;
  coordinate?: string | null;
  status?: ProjectStatus;
}

// 部门信息（对应后端 DepartmentOut）
export interface Department {
  id: number;
  name: string;
  code: string;
  parent_id: number | null;
  leader: string | null;
  phone: string | null;
  sort: number;
  status: boolean;
  remark: string | null;
  created_at: string | null;
}

// ===================== 设备管理 =====================
export type DeviceType = "locate" | "anti_intrusion" | "train_approach";

// 设备信息（三类设备统一结构，无关字段为 null）
export interface Device {
  id: number;
  device_type: DeviceType;
  project_id: number | null;
  name: string;
  device_no: string;
  sn: string | null;
  status: string;
  function: string | null;
  longitude: number | null;
  latitude: number | null;
  direction: string | null;
  created_by: number | null;
  created_at: string | null;
}

export interface DevicePage {
  items: Device[];
  total: number;
  page: number;
  size: number;
}

export interface DeviceCreate {
  device_type: DeviceType;
  project_id: number;
  name: string;
  device_no: string;
  sn?: string | null;
  status?: string;
  function?: string | null;
  longitude?: number | null;
  latitude?: number | null;
  direction?: string | null;
}

export interface DeviceUpdate {
  project_id?: number;
  name?: string;
  device_no?: string;
  sn?: string | null;
  status?: string;
  function?: string | null;
  longitude?: number | null;
  latitude?: number | null;
  direction?: string | null;
}

// ===================== 人员管理 =====================
export interface Person {
  id: number;
  project_id: number | null;
  person_no: string;
  name: string;
  gender: string | null;
  phone: string | null;
  person_type: string | null;
  icon: string | null;
  device_no: string | null;
  created_by: number | null;
  created_at: string | null;
}

export interface PersonPage {
  items: Person[];
  total: number;
  page: number;
  size: number;
}

export interface PersonCreate {
  project_id: number;
  person_no: string;
  name: string;
  gender?: string | null;
  phone?: string | null;
  person_type?: string | null;
  device_no?: string | null;
}

export interface PersonUpdate {
  project_id?: number;
  person_no?: string;
  name?: string;
  gender?: string | null;
  phone?: string | null;
  person_type?: string | null;
  device_no?: string | null;
}

// ===================== 大型机械管理 =====================
export interface Machine {
  id: number;
  project_id: number | null;
  machine_no: string;
  machine_type: string | null;
  spec_model: string | null;
  description: string | null;
  created_by: number | null;
  created_at: string | null;
}

export interface MachinePage {
  items: Machine[];
  total: number;
  page: number;
  size: number;
}

export interface MachineCreate {
  project_id: number;
  machine_no: string;
  machine_type?: string | null;
  spec_model?: string | null;
  description?: string | null;
}

export interface MachineUpdate {
  project_id?: number;
  machine_no?: string;
  machine_type?: string | null;
  spec_model?: string | null;
  description?: string | null;
}

// ===================== 电子围栏管理 =====================
export interface Fence {
  id: number;
  project_id: number | null;
  name: string;
  fence_type: string | null;
  enabled: boolean;
  geometry_wkt: string | null;
  created_by: number | null;
  created_at: string | null;
}

export interface FencePage {
  items: Fence[];
  total: number;
  page: number;
  size: number;
}

export interface FenceCreate {
  project_id: number;
  name: string;
  fence_type?: string | null;
  enabled?: boolean;
  geometry_wkt?: string | null;
}

export interface FenceUpdate {
  project_id?: number;
  name?: string;
  fence_type?: string | null;
  enabled?: boolean | null;
  geometry_wkt?: string | null;
}

// ===================== 告警管理 =====================
export type AlarmStatus = "告警开始" | "告警结束" | "已消警";
export type AlarmLevel = "严重" | "警告" | "提示";
export type HandleStatus =
  | "待处理"
  | "已处理"
  | "已忽略"
  | "已确认"
  | "已消警";

export interface Alarm {
  id: number;
  project_id: number | null;
  alarm_type: string | null;
  device_type: string;
  device_name: string | null;
  device_no: string | null;
  alarm_info: string | null;
  alarm_status: string;
  alarm_level: string | null;
  handle_status: string;
  handle_content: string | null;
  fence_name: string | null;
  work_plan_id: number | null;
  media_urls: string[] | null;
  alarm_time: string | null;
  hazard_id: number | null;
}

export interface AlarmPage {
  items: Alarm[];
  total: number;
}

export interface AlarmHandleRequest {
  handle_status: string;
  content?: string | null;
}

// ===================== 媒体管理 =====================
export interface MediaMeta {
  key: string;
  url: string;
  filename: string;
  content_type: string;
  size: number;
  bucket: string;
  presigned_url?: string | null;
}

// ===================== 通用附件（关联任意实体） =====================
export interface Attachment {
  id: number;
  entity_type: string;
  entity_id: number;
  media_key: string;
  url: string;
  filename: string;
  content_type: string;
  size: number;
  created_at: string | null;
  created_by: number | null;
}

export interface AlarmConfig {
  id: number;
  enable_popup: boolean;
  enable_voice: boolean;
  voice_file: string | null;
  distance_machine: number;
  distance_handheld: number;
  distance_badge: number;
  distance_band: number;
}

// ===================== 作业计划 =====================
export type WorkPlanStatus = "草稿" | "执行中" | "已完成";

export interface WorkPlanRule {
  monitor_target?: string | null;
  trigger_condition?: string | null;
  trigger_conditions?: string[] | null;
  time_range?: string | null;
  dwell_time?: number | null;
}

export interface DeviceBinding {
  device_type: string;
  device_no: string;
}

export interface BoundPerson {
  id: number;
  name: string;
}

export interface BoundMachine {
  id: number;
  name: string;
}

export interface BoundDevice {
  device_type: string;
  device_no: string;
  name?: string | null;
}

export interface BoundFence {
  id: number;
  name: string | null;
}

export interface WorkPlan {
  id: number;
  project_id: number | null;
  project_name?: string | null;
  name: string;
  is_start: boolean;
  description?: string | null;
  plan_time?: string | null;
  plan_start?: string | null;
  plan_end?: string | null;
  status: WorkPlanStatus;
  active?: boolean;
  is_template?: boolean;
  rule?: WorkPlanRule | null;
  created_by?: number | null;
  created_at?: string | null;
  persons?: BoundPerson[];
  machines?: BoundMachine[];
  devices?: BoundDevice[];
  fences?: BoundFence[];
}

export interface WorkPlanPage {
  items: WorkPlan[];
  total: number;
}

export interface WorkPlanCreate {
  project_id?: number | null;
  name: string;
  is_start?: boolean;
  description?: string | null;
  plan_time?: string | null;
  plan_start?: string | null;
  plan_end?: string | null;
  status?: WorkPlanStatus;
  rule?: WorkPlanRule | null;
  person_ids?: number[];
  machine_ids?: number[];
  device_bindings?: DeviceBinding[];
  fence_ids?: number[];
}

export interface WorkPlanUpdate {
  project_id?: number | null;
  name?: string;
  is_start?: boolean;
  description?: string | null;
  plan_time?: string | null;
  plan_start?: string | null;
  plan_end?: string | null;
  status?: WorkPlanStatus;
  rule?: WorkPlanRule | null;
  person_ids?: number[];
  machine_ids?: number[];
  device_bindings?: DeviceBinding[];
  fence_ids?: number[];
}

// ===================== 巡检打卡（P3·⑨） =====================
export interface InspectionRecord {
  id: number;
  task_id: number;
  project_id?: number | null;
  checkin_by_name?: string | null;
  checkin_at?: string | null;
  lng?: number | null;
  lat?: number | null;
  result: string;
  note?: string | null;
  hazard_id?: number | null;
}

export interface InspectionTask {
  id: number;
  project_id?: number | null;
  project_name?: string | null;
  name: string;
  content?: string | null;
  assignee_id?: number | null;
  assignee_name?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  status: string;
  required_checkins: number;
  checkin_count: number;
  abnormal_count: number;
  records: InspectionRecord[];
}

export interface InspectionTaskPage {
  total: number;
  items: InspectionTask[];
  page: number;
  size: number;
}

export interface InspectionStats {
  task_total: number;
  by_status: Record<string, number>;
  checkin_total: number;
  abnormal_total: number;
}

// ===================== 视频 AI（P3·⑧） =====================
export interface VideoChannel {
  id: number;
  project_id?: number | null;
  project_name?: string | null;
  name: string;
  channel_no: string;
  stream_url?: string | null;
  vendor?: string | null;
  location_desc?: string | null;
  lng?: number | null;
  lat?: number | null;
  status: string;
  ai_enabled: boolean;
  created_at?: string | null;
}

export interface VideoEvent {
  id: number;
  channel_id: number;
  channel_name?: string | null;
  channel_no?: string | null;
  project_id?: number | null;
  event_type: string;
  event_type_label?: string | null;
  confidence?: number | null;
  snapshot_url?: string | null;
  event_time?: string | null;
  detail?: string | null;
  handled: boolean;
  alarm_id?: number | null;
  created_at?: string | null;
}

// ===================== 设备健康（P3·⑫） =====================
export interface DeviceHealthItem {
  id: number;
  device_type: string;
  type_label: string;
  name: string;
  device_no: string;
  project_id?: number | null;
  project_name?: string | null;
  status?: string | null;
  online: boolean;
  last_report_time?: string | null;
  age_seconds?: number | null;
  report_count: number;
  alarm_count: number;
  health_score: number;
  online_state?: string | null;
  health_level?: string | null;
}

export interface DeviceHealthResp {
  window_hours: number;
  threshold_seconds: number;
  total: number;
  online: number;
  offline: number;
  items: DeviceHealthItem[];
}

// ===================== 对比大屏（P3·⑪） =====================
export interface ProjectCompareItem {
  project_id: number;
  project_name: string;
  device_count: number;
  person_count: number;
  machine_count: number;
  fence_count: number;
  active_plan_count: number;
  alarm_count: number;
  unhandled_alarm_count: number;
  open_hazard_count: number;
  overdue_hazard_count: number;
  risk_score: number;
  risk_index?: number;
  risk_level?: string | null;
}

export interface ProjectCompareResp {
  window_days: number;
  items: ProjectCompareItem[];
}

// ===================== 系统管理：用户 =====================
export interface SysUser {
  id: number;
  username: string;
  nickname: string | null;
  email: string | null;
  phone: string | null;
  dept_id: number | null;
  status: boolean;
  is_superuser: boolean;
  roles: string[];
  permissions: string[];
  last_login_at: string | null;
  created_at: string | null;
}

export interface UserPage {
  items: SysUser[];
  total: number;
  page: number;
  size: number;
}

export interface UserCreate {
  username: string;
  password: string;
  nickname?: string | null;
  email?: string | null;
  phone?: string | null;
  dept_id?: number | null;
  role_codes: string[];
  status?: boolean;
}

export interface UserUpdate {
  nickname?: string | null;
  email?: string | null;
  phone?: string | null;
  dept_id?: number | null;
  status?: boolean;
  role_codes?: string[] | null;
  password?: string | null;
}

// ===================== 系统管理：角色 =====================
export interface Role {
  id: number;
  name: string;
  code: string;
  data_scope: number;
  is_system: boolean;
  remark: string | null;
  status: boolean;
  permission_codes: string[];
  dept_ids: number[];
}

export interface RoleCreate {
  name: string;
  code: string;
  data_scope?: number;
  dept_ids?: number[];
  remark?: string | null;
}

export interface RoleUpdate {
  name?: string;
  data_scope?: number;
  remark?: string | null;
  status?: boolean;
}

// ===================== 系统管理：权限 =====================
export interface Permission {
  id: number;
  name: string;
  code: string;
  type: number;
  parent_id: number | null;
  path: string | null;
  icon: string | null;
  sort: number;
  status: boolean;
}

// ===================== 系统管理：部门（创建/编辑） =====================
export interface DepartmentCreate {
  name: string;
  code: string;
  parent_id?: number | null;
  leader?: string | null;
  phone?: string | null;
  sort?: number;
  status?: boolean;
  remark?: string | null;
}

export interface DepartmentUpdate {
  name?: string;
  parent_id?: number | null;
  leader?: string | null;
  phone?: string | null;
  sort?: number;
  status?: boolean;
  remark?: string | null;
}

// ===================== 地图 / 轨迹 =====================
// 地图打点设备（已统一为 GCJ-02 坐标，可直接上高德地图）
export interface MapDevice {
  device_no: string;
  name: string;
  device_type: DeviceType;
  lng: number;
  lat: number;
  status: string;
  live: boolean;
}

// 地图围栏（geometry_wkt 为 WGS-84，上图时前端转换为 GCJ-02）
export interface MapFence {
  id: number;
  name: string;
  geometry_wkt: string | null;
}

// 轨迹回放单点（后端已转换 gcj02）
export interface TrajectoryPoint {
  device_no: string;
  device_name: string | null;
  report_time: string | null;
  longitude: number | null;
  latitude: number | null;
  gcj02: { lng: number; lat: number } | null;
  speed: number | null;
  status: string;
}

// ===================== 大屏 =====================
export interface DashboardCounts {
  projects: number;
  devices: number;
  devices_online: number;
  devices_offline: number;
  persons: number;
  machines: number;
  fences: number;
  alarms: number;
  alarms_today: number;
  // 周期联动：所选时间窗内告警合计 + 当前周期（窗口末端所属周期）告警数
  alarms_window?: number;
  alarms_current_period?: number;
}

export interface DashboardStats {
  counts: DashboardCounts;
  device_by_type: { device_type: string; count: number }[];
  alarm_by_level: { level: string; count: number }[];
  alarm_by_handle: { status: string; count: number }[];
  project_status: { status: string; count: number }[];
  alarm_trend_7d: { date: string; count: number }[];
  // 周期联动趋势：按 granularity 聚合的窗口内分布（与告警报表 by_period 同一口径）
  alarm_trend_period: {
    period: string;
    count: number;
    by_type: Record<string, number>;
    by_level: Record<string, number>;
  }[];
  trend_granularity?: string;
  trend_start?: string;
  trend_end?: string;
  // 当前周期 key（窗口末端所属周期，如 2026-07-16 / 2026-W29 / 2026-07）
  current_period?: string;
  // 设备在线率（实时心跳）：总/在线/在线率%/区间活跃设备数（随窗口周期联动）
  device_stats?: DeviceStats;
  // 围栏统计：总/启用/窗口内监控围栏数/按类型（随窗口周期联动）
  fence_stats?: FenceStats;
}

// 设备在线率（与后端 /v1/dashboard/stats 的 device_stats 对齐）
export interface DeviceStats {
  total: number;
  online: number;
  online_rate: number; // 百分比，如 100.0
  window_active: number; // 所选窗口内至少上报一次的设备数
}

// 围栏统计（与后端 /v1/dashboard/stats 的 fence_stats 对齐）
export interface FenceStats {
  total: number;
  enabled: number;
  monitored_in_window: number; // 窗口内被激活作业计划监控的围栏数
  by_type: { type: string; count: number }[];
}

export interface RecentAlarm {
  id: number;
  alarm_type: string | null;
  device_type: string | null;
  device_name: string | null;
  device_no: string | null;
  alarm_level: string | null;
  alarm_info: string | null;
  alarm_status: string | null;
  handle_status: string | null;
  fence_name: string | null;
  alarm_time: string | null;
  project_id: number | null;
}
