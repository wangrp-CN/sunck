<script setup lang="ts">
// 侧边导航菜单（提取自 DefaultLayout），桌面侧栏与移动抽屉共用，避免重复维护。
// 菜单分组严格对齐《系统总体功能结构图》的 8 个一级模块。
import { computed } from "vue";
import { useRoute } from "vue-router";
import {
  DataLine,
  Position,
  Folder,
  TrendCharts,
  MagicStick,
  Bell,
  Connection,
  Histogram,
  Cpu,
  Promotion,
  User,
  Setting,
  Location,
  Notebook,
  Compass,
  VideoCamera,
  Warning,
  Monitor,
  Clock,
  Switch,
  VideoPlay,
} from "@element-plus/icons-vue";

const route = useRoute();
// 普通路由用 path 匹配；带 query 的菜单项（如列车接近告警）用 fullPath 精确匹配高亮
const activeMenu = computed(() => {
  if (route.path === "/alarms" && route.query.alarm_type) {
    return route.fullPath;
  }
  return route.path;
});
// 移动端点击菜单项后由父组件关闭抽屉
const emit = defineEmits<{ (e: "navigate"): void }>();
</script>

<template>
  <el-menu
    :default-active="activeMenu"
    router
    class="menu"
    @select="emit('navigate')"
  >
    <!-- ① 大屏 -->
    <el-sub-menu index="/dashboard-group">
      <template #title>
        <el-icon><DataLine /></el-icon>
        <span>大屏</span>
      </template>
      <el-menu-item index="/dashboard">
        <el-icon><DataLine /></el-icon>
        <span>监控大屏</span>
      </el-menu-item>
      <el-menu-item index="/projects/compare">
        <el-icon><TrendCharts /></el-icon>
        <span>对比大屏</span>
      </el-menu-item>
      <el-menu-item index="/track">
        <el-icon><VideoPlay /></el-icon>
        <span>设备轨迹页(轨迹回放)</span>
      </el-menu-item>
    </el-sub-menu>

    <!-- ② 项目管理 -->
    <el-menu-item index="/projects">
      <el-icon><Folder /></el-icon>
      <span>项目管理</span>
    </el-menu-item>

    <!-- ③ 作业管理 -->
    <el-menu-item index="/jobs">
      <el-icon><Notebook /></el-icon>
      <span>作业管理</span>
    </el-menu-item>

    <!-- ④ 电子围栏管理 -->
    <el-menu-item index="/fences">
      <el-icon><Location /></el-icon>
      <span>电子围栏管理</span>
    </el-menu-item>

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
        <el-icon><Monitor /></el-icon>
        <span>设备健康</span>
      </el-menu-item>
      <el-menu-item index="/devices/commands">
        <el-icon><Promotion /></el-icon>
        <span>指令下发记录</span>
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

    <!-- ⑥ 人员机械管理 -->
    <el-sub-menu index="/person-machine-group">
      <template #title>
        <el-icon><User /></el-icon>
        <span>人员机械管理</span>
      </template>
      <el-menu-item index="/persons">
        <el-icon><User /></el-icon>
        <span>人员管理</span>
      </el-menu-item>
      <el-menu-item index="/machines">
        <el-icon><Setting /></el-icon>
        <span>机械管理</span>
      </el-menu-item>
      <el-menu-item index="/inspections">
        <el-icon><Compass /></el-icon>
        <span>巡检打卡</span>
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
        <el-icon><Warning /></el-icon>
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
        <el-icon><Bell /></el-icon>
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
          <el-icon><Bell /></el-icon>
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
      <el-menu-item index="/system/users">用户管理</el-menu-item>
      <el-menu-item index="/system/roles">角色管理</el-menu-item>
      <el-menu-item index="/system/departments">部门管理</el-menu-item>
      <el-menu-item index="/dicts">数据字典</el-menu-item>
      <el-menu-item index="/maps">地图维护</el-menu-item>
      <el-menu-item index="/audit-logs">操作审计</el-menu-item>
      <el-menu-item index="/intelligence/report-center">报表中心</el-menu-item>
    </el-sub-menu>
  </el-menu>
</template>

<style scoped>
.menu {
  border-right: none;
  background: #001529;
}
.menu :deep(.el-menu-item) {
  color: #c0c4cc;
}
.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #1890ff;
}
</style>
