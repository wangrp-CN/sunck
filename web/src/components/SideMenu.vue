<script setup lang="ts">
// 侧边导航菜单（提取自 DefaultLayout），桌面侧栏与移动抽屉共用，避免重复维护。
// 菜单分组严格对齐《系统总体功能结构图》的 8 个一级模块。
import { computed } from "vue";
import { useRoute } from "vue-router";
import {
  DataLine,
  DataBoard,
  Position,
  Folder,
  MagicStick,
  Bell,
  Connection,
  Histogram,
  Cpu,
  Promotion,
  User,
  Setting,
  Notebook,
  Compass,
  VideoCamera,
  Warning,
  Monitor,
  Clock,
  Switch,
  VideoPlay,
  LocationFilled,
  Tools,
  List,
  Avatar,
  OfficeBuilding,
  Collection,
  MapLocation,
  Files,
  EditPen,
  Document,
  ChatDotRound,
  ChatLineRound,
  Odometer,
} from "@element-plus/icons-vue";

// 折叠态由父层（DefaultLayout）控制：窄桌面/手动收起时仅显示图标
const props = defineProps<{ collapse?: boolean }>();

const route = useRoute();
// 普通路由用 path 匹配；带 query 的菜单项（如列车接近告警）用 fullPath 精确匹配高亮
const activeMenu = computed(() => {
  if (route.path === "/alarms" && route.query.alarm_type) {
    return route.fullPath;
  }
  // 告警详情页：菜单指向无 id 的 /alarms/detail，进入后会 replace 成
  // /alarms/{id}/detail，需回落到菜单 index 才能保持高亮
  if (/^\/alarms\/\d+\/detail$/.test(route.path)) {
    return "/alarms/detail";
  }
  return route.path;
});
// 移动端点击菜单项后由父组件关闭抽屉
const emit = defineEmits<{ (e: "navigate"): void }>();
</script>

<template>
  <el-menu
    :default-active="activeMenu"
    :collapse="props.collapse"
    :collapse-transition="false"
    router
    class="menu"
    @select="emit('navigate')"
  >
    <!-- ① 大屏（与后端模块名对齐） -->
    <el-sub-menu index="/dashboard-group">
      <template #title>
        <el-icon><DataLine /></el-icon>
        <span>大屏</span>
      </template>
      <el-menu-item index="/dashboard">
        <el-icon><DataBoard /></el-icon>
        <span>大屏首页</span>
      </el-menu-item>
      <el-menu-item index="/track">
        <el-icon><VideoPlay /></el-icon>
        <span>设备轨迹页</span>
      </el-menu-item>
      <el-menu-item index="/projects/detail">
        <el-icon><DataBoard /></el-icon>
        <span>项目详情页</span>
      </el-menu-item>
      <el-menu-item index="/alarms/detail">
        <el-icon><Warning /></el-icon>
        <span>告警详情页</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ② 项目管理 -->
    <el-sub-menu index="/projects-group">
      <template #title>
        <el-icon><Folder /></el-icon>
        <span>项目管理</span>
      </template>
      <el-menu-item index="/projects/list">
        <el-icon><Folder /></el-icon>
        <span>项目列表</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ③ 作业计划（与后端模块名对齐） -->
    <el-sub-menu index="/job-group">
      <template #title>
        <el-icon><Notebook /></el-icon>
        <span>作业计划</span>
      </template>
      <el-menu-item index="/jobs">
        <el-icon><List /></el-icon>
        <span>作业列表</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ④ 电子围栏（与后端模块名对齐） -->
    <el-sub-menu index="/fence-group">
      <template #title>
        <el-icon><LocationFilled /></el-icon>
        <span>电子围栏</span>
      </template>
      <el-menu-item index="/fences/list">
        <el-icon><LocationFilled /></el-icon>
        <span>电子围栏列表</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ⑤ 设备管理 -->
    <el-sub-menu index="/devices-group">
      <template #title>
        <el-icon><Cpu /></el-icon>
        <span>设备管理</span>
      </template>
      <el-menu-item index="/devices">
        <el-icon><Cpu /></el-icon>
        <span>设备列表</span>
      </el-menu-item>
      <el-menu-item index="/devices/online">
        <el-icon><Monitor /></el-icon>
        <span>在线看板</span>
      </el-menu-item>
      <el-menu-item index="/devices/health">
        <el-icon><Odometer /></el-icon>
        <span>设备健康</span>
      </el-menu-item>
      <el-menu-item index="/devices/commands">
        <el-icon><Promotion /></el-icon>
        <span>指令下发记录</span>
      </el-menu-item>
      <el-menu-item index="/devices/locate">
        <el-icon><LocationFilled /></el-icon>
        <span>人机定位设备列表</span>
      </el-menu-item>
      <el-menu-item index="/devices/anti-intrusion">
        <el-icon><Warning /></el-icon>
        <span>大机防侵限设备列表</span>
      </el-menu-item>
      <el-menu-item index="/devices/train-approach">
        <el-icon><Bell /></el-icon>
        <span>列车接近报警设备列表</span>
      </el-menu-item>
      <el-menu-item index="/realtime">
        <el-icon><Position /></el-icon>
        <span>实时监控</span>
      </el-menu-item>
      <el-menu-item index="/videos">
        <el-icon><VideoCamera /></el-icon>
        <span>视频AI</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ⑥ 人员机械管理（与后端 person 模块对齐；巡检归属人员侧） -->
    <el-sub-menu index="/person-group">
      <template #title>
        <el-icon><User /></el-icon>
        <span>人员机械管理</span>
      </template>
      <el-menu-item index="/persons">
        <el-icon><User /></el-icon>
        <span>人员列表</span>
      </el-menu-item>
      <el-menu-item index="/inspections">
        <el-icon><Compass /></el-icon>
        <span>巡检打卡</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ⑥-2 机械管理（与后端 machine 模块对齐） -->
    <el-sub-menu index="/machine-group">
      <template #title>
        <el-icon><Tools /></el-icon>
        <span>机械管理</span>
      </template>
      <el-menu-item index="/machines">
        <el-icon><Tools /></el-icon>
        <span>机械管理</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ⑦ 告警管理 -->
    <el-sub-menu index="/alarm-group">
      <template #title>
        <el-icon><Warning /></el-icon>
        <span>告警管理</span>
      </template>
      <el-menu-item index="/alarms">
        <el-icon><Warning /></el-icon>
        <span>设备告警</span>
      </el-menu-item>
      <el-menu-item index="/alarms?alarm_type=train_approach">
        <el-icon><Position /></el-icon>
        <span>列车接近告警</span>
      </el-menu-item>
      <el-menu-item index="/dispatch">
        <el-icon><Promotion /></el-icon>
        <span>根因派单</span>
      </el-menu-item>
      <el-menu-item index="/duty-roster">
        <el-icon><Clock /></el-icon>
        <span>值班排班</span>
      </el-menu-item>
      <el-menu-item index="/hazards">
        <el-icon><Bell /></el-icon>
        <span>隐患治理</span>
      </el-menu-item>
      <el-menu-item index="/notifications">
        <el-icon><ChatDotRound /></el-icon>
        <span>消息中心</span>
      </el-menu-item>
      <el-menu-item index="/intelligence/correlation">
        <el-icon><Connection /></el-icon>
        <span>跨设备根因关联</span>
      </el-menu-item>
      <el-menu-item index="/intelligence/correlation-compare">
        <el-icon><Histogram /></el-icon>
        <span>关联热力对比</span>
      </el-menu-item>
      <el-sub-menu index="/alarm-config-group">
        <template #title>
          <el-icon><Switch /></el-icon>
          <span>告警配置</span>
        </template>
        <el-menu-item index="/alarm-policies">
          <el-icon><Switch /></el-icon>
          <span>告警策略</span>
        </el-menu-item>
        <el-menu-item index="/playbooks">
          <el-icon><Notebook /></el-icon>
          <span>处置预案/知识库</span>
        </el-menu-item>
        <el-menu-item index="/intelligence/threshold">
          <el-icon><MagicStick /></el-icon>
          <span>阈值自学习</span>
        </el-menu-item>
        <el-menu-item index="/intelligence/subscriptions">
          <el-icon><ChatLineRound /></el-icon>
          <span>报告订阅</span>
        </el-menu-item>
      </el-sub-menu>
    </el-sub-menu>

    <!-- ⑧ 系统管理 -->
    <el-sub-menu index="/system">
      <template #title>
        <el-icon><Setting /></el-icon>
        <span>系统管理</span>
      </template>
      <el-menu-item index="/system/users">
        <el-icon><User /></el-icon>
        <span>用户管理</span>
      </el-menu-item>
      <el-menu-item index="/system/roles">
        <el-icon><Avatar /></el-icon>
        <span>角色管理</span>
      </el-menu-item>
      <el-menu-item index="/system/departments">
        <el-icon><OfficeBuilding /></el-icon>
        <span>部门管理</span>
      </el-menu-item>
      <el-menu-item index="/system/menus">
        <el-icon><Switch /></el-icon>
        <span>菜单管理</span>
      </el-menu-item>
      <el-menu-item index="/system/logs">
        <el-icon><Files /></el-icon>
        <span>日志管理</span>
      </el-menu-item>
      <el-menu-item index="/dicts">
        <el-icon><Collection /></el-icon>
        <span>数据字典</span>
      </el-menu-item>
      <el-sub-menu index="/maps-group">
        <template #title>
          <el-icon><MapLocation /></el-icon>
          <span>地图维护</span>
        </template>
        <el-menu-item index="/maps">
          <el-icon><Files /></el-icon>
          <span>地图资源库</span>
        </el-menu-item>
        <el-menu-item index="/maps/draw">
          <el-icon><EditPen /></el-icon>
          <span>手动绘制</span>
        </el-menu-item>
      </el-sub-menu>
      <el-menu-item index="/audit-logs">
        <el-icon><Document /></el-icon>
        <span>操作审计</span>
      </el-menu-item>
      <el-menu-item index="/intelligence/report-center">
        <el-icon><Histogram /></el-icon>
        <span>报表中心</span>
      </el-menu-item>
    </el-sub-menu>
  </el-menu>
</template>

<style scoped>
.menu {
  border-right: none;
  /* 白底侧栏：菜单本身透明，底色由父层 aside 的白底承载 */
  background: transparent;
  /* 长菜单在矮屏内独立滚动，避免溢出遮挡底部 */
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
}
/* 细滚动条，弱化存在感 */
.menu::-webkit-scrollbar {
  width: 6px;
}
.menu::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
  border-radius: 3px;
}
.menu::-webkit-scrollbar-track {
  background: transparent;
}

/* 一级模块：卡片化分组（玻璃拟态下，以「明度差 + 柔和投影」区分，不用分割线） */
.menu :deep(.el-menu) {
  background: transparent;
}
.menu :deep(.el-menu > .el-sub-menu > .el-sub-menu__title),
.menu :deep(.el-menu > .el-menu-item) {
  margin: 6px 10px;
  height: 46px;
  line-height: 46px;
  border-radius: 8px;
  color: #5b6675;
  font-size: 14px;
  font-weight: 400;
  letter-spacing: 0.3px;
  /* 白底侧栏：模块以「略深面板 + 柔和投影」区分，无分割线 */
  background: rgba(0, 0, 0, 0.03);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}
/* 模块之间靠留白与明度差分隔，移除分割线 */
.menu :deep(.el-menu > .el-sub-menu:not(:first-child) > .el-sub-menu__title),
.menu :deep(.el-menu > .el-menu-item:not(:first-child)) {
  margin-top: 8px;
}
.menu :deep(.el-menu > .el-sub-menu > .el-sub-menu__title):hover,
.menu :deep(.el-menu > .el-menu-item):hover {
  background: rgba(24, 144, 255, 0.08);
  color: #1890ff;
}
/* 当前展开的一级模块：强调所属分类（品牌色浅底，文字点亮） */
.menu :deep(.el-sub-menu.is-opened > .el-sub-menu__title) {
  color: #1890ff;
  background: rgba(24, 144, 255, 0.1);
}
/* 一级图标统一样式 */
.menu :deep(.el-menu > .el-sub-menu > .el-sub-menu__title .el-icon),
.menu :deep(.el-menu > .el-menu-item .el-icon) {
  font-size: 18px;
}

/* 内联子项：与父级分组(.el-sub-menu__title)视觉样式【完全一致】——
   同一字号(14px)/字重(600)/颜色(#5b6675)/字间距(0.3px)/字体，
   同一高度(46px)/圆角(8px)/面板(rgba(0,0,0,.03)+柔和投影)。
   层级差异仅由 padding-left 缩进体现，菜单名称样式在父子层级间零差异。
   对齐公式：子项盒子左缘在父级 margin 内(10px)，+ padding-left 20px = 30px，
   与父级标题图标/名称左缘(10+20)重合 → 子项名称与父级名称左对齐。
   左 margin 保持 0 以保留该缩进（上下/右与父级一致）。 */
.menu :deep(.el-menu--inline) {
  background: transparent;
  padding: 2px 0;
}
.menu :deep(.el-menu--inline .el-menu-item) {
  height: 46px;
  line-height: 46px;
  margin: 6px 10px 6px 0;
  padding-left: 20px !important;
  border-radius: 8px;
  color: #5b6675;
  background: rgba(0, 0, 0, 0.03);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  font-size: 14px;
  font-weight: 400;
  letter-spacing: 0.3px;
}
.menu :deep(.el-menu--inline .el-menu-item):hover {
  color: #1890ff;
  background: rgba(24, 144, 255, 0.08);
}

/* 激活态：左侧品牌色高亮条 + 浅蓝底（靠颜色/高亮条区分，不靠字重，保持全菜单字重一致） */
.menu :deep(.el-menu--inline .el-menu-item.is-active),
.menu :deep(.el-menu > .el-menu-item.is-active) {
  color: #1890ff;
  font-weight: 400;
  background: rgba(24, 144, 255, 0.1);
  border-left: 3px solid #1890ff;
}

/* 菜单名称字重【单一来源·全局统一】：父级(.el-sub-menu__title) 与 子级(.el-menu-item)
   在任意层级（顶层 / 内联 / 嵌套子分组标题）均使用同一 font-weight(400)，
   彻底消除子菜单相对父级加粗的视觉差异，保证整棵菜单字体粗细完全一致。
   嵌套子分组标题（如「告警配置」「地图维护」）此前未被顶层选择器覆盖、沿用 EP 默认，
   此处一并归一，避免子项(600)比该父级标题(默认 normal)粗的问题。 */
.menu :deep(.el-sub-menu__title),
.menu :deep(.el-menu-item) {
  font-weight: 400;
}
.menu :deep(.el-menu--inline .el-menu-item.is-active .el-icon) {
  color: #1890ff;
}

/* 折叠态：仅图标，宽度由父层容器控制 */
.menu.el-menu--collapse {
  width: 100%;
}
.menu :deep(.el-menu--collapse .el-sub-menu__title),
.menu :deep(.el-menu--collapse .el-menu-item) {
  margin: 6px 10px;
  text-align: center;
}
</style>
