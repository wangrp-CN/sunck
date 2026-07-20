// 共享构建插件：Element Plus 按需引入（tree-shaking）
// - AutoImport：自动注入 ElMessage / ElMessageBox / ElNotification 等 API 及其样式
// - Components：模板中 <el-xxx> 组件按需引入并自动引入对应 CSS；
//   ElementPlusResolver 默认 resolveIcons=true，会同时解析模板中的 <Icon/> 图标
// 供 vite.config.ts 与 vitest.config.ts 复用，保证构建与测试环境一致。
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

export interface ElementPlusPluginsOpts {
  // 是否注入组件/API 的 CSS（构建时 true，测试时 false 以规避 jsdom 无法加载 .css）
  importStyle?: boolean;
  // 是否生成类型声明文件（构建时 true，测试时 false 避免重复写入）
  emitDts?: boolean;
}

export function elementPlusPlugins(opts: ElementPlusPluginsOpts = {}) {
  const importStyle = opts.importStyle ?? true;
  const emitDts = opts.emitDts ?? true;
  return [
    AutoImport({
      // 仅解析 Element Plus 的 API（ElMessage 等），不接管 vue 原生 API
      resolvers: [ElementPlusResolver({ importStyle, resolveIcons: false })],
      ...(emitDts ? { dts: "src/auto-imports.d.ts" } : {}),
      eslintrc: { enabled: false },
    }),
    Components({
      resolvers: [ElementPlusResolver({ importStyle, resolveIcons: false })],
      // 不生成组件类型声明：本项目 el-table 等表格事件处理函数长期存在
      // 「表格行 => 领域对象」的类型隐患（DefaultRow 不可赋值给 Machine/Person 等），
      // 生成组件声明会把该隐患暴露为 type-check 错误。运行时按需引入不受影响。
      dts: false,
    }),
  ];
}
