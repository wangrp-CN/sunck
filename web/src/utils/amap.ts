// 高德 JS API 2.0 动态加载器（仅前端地图使用）。
//
// 设计要点：
// 1. 动态注入 <script>，避免「无 Key 时仍向高德发起请求」导致控制台报错；
// 2. 占位符（your-xxx）视作未配置，直接降级，绝不尝试加载；
// 3. JS API 2.0 必须先在 window._AMapSecurityConfig 注入安全密钥，
//    否则会抛 AMapSecurityConfigMissingError（见仓库根 AMAP_KEY_SETUP_GUIDE.md）。
//
// 真实使用时，在 web/.env 配置：
//   VITE_AMAP_KEY=你的高德Web端JS API Key
//   VITE_AMAP_SECURITY_CODE=你的高德安全密钥

const PLACEHOLDER = "your-amap-web-service-key";

function rawKey(): string {
  return (import.meta.env.VITE_AMAP_KEY as string | undefined) || "";
}

function rawSecurity(): string {
  return (import.meta.env.VITE_AMAP_SECURITY_CODE as string | undefined) || "";
}

/** 是否真正配置了可用 Key（占位符视作未配置）。 */
export function isAmapEnabled(): boolean {
  const k = rawKey();
  return k !== "" && k !== PLACEHOLDER && !k.startsWith("your-");
}

export function amapKey(): string {
  return isAmapEnabled() ? rawKey() : "";
}

export function amapSecurity(): string {
  return rawSecurity();
}

let loader: Promise<any> | null = null;

/** 返回已加载的全局 AMap 构造器；未配置或加载失败则 reject。 */
export function loadAMap(): Promise<any> {
  const key = amapKey();
  if (!key) {
    return Promise.reject(new Error("AMAP_KEY_NOT_SET"));
  }
  // @ts-ignore 全局对象
  if (window.AMap) {
    // @ts-ignore
    return Promise.resolve(window.AMap);
  }
  if (loader) return loader;

  loader = new Promise((resolve, reject) => {
    // @ts-ignore 注入安全密钥（必须在地图脚本之前）
    window._AMapSecurityConfig = { securityJsCode: amapSecurity() };
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`;
    script.onerror = () => {
      loader = null;
      reject(new Error("AMAP_LOAD_FAILED"));
    };
    script.onload = () => {
      // @ts-ignore
      if (window.AMap) resolve(window.AMap);
      else {
        loader = null;
        reject(new Error("AMAP_LOAD_FAILED"));
      }
    };
    document.head.appendChild(script);
  });
  return loader;
}
