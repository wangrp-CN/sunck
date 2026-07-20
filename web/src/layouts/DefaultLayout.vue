<script setup lang="ts">
import { computed } from "vue";
import {
  DataLine,
  Position,
  Folder,
  Cpu,
  User,
  Setting,
  Location,
  Notebook,
  Warning,
} from "@element-plus/icons-vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const activeMenu = computed(() => route.path);

const nickname = computed(() => auth.user?.nickname || auth.user?.username || "未登录");

async function handleLogout() {
  await auth.logout();
  ElMessage.success("已退出登录");
  router.push({ name: "login" });
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">涉铁监控平台</div>
      <el-menu :default-active="activeMenu" router class="menu">
        <el-menu-item index="/dashboard">
          <el-icon><DataLine /></el-icon>
          <span>监控大屏</span>
        </el-menu-item>
        <el-menu-item index="/realtime">
          <el-icon><Position /></el-icon>
          <span>实时监控</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目管理</span>
        </el-menu-item>
        <el-sub-menu index="/devices-group">
          <template #title>
            <el-icon><Cpu /></el-icon>
            <span>设备管理</span>
          </template>
          <el-menu-item index="/devices">设备列表</el-menu-item>
          <el-menu-item index="/devices/online">在线看板</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/persons">
          <el-icon><User /></el-icon>
          <span>人员管理</span>
        </el-menu-item>
        <el-menu-item index="/machines">
          <el-icon><Setting /></el-icon>
          <span>机械管理</span>
        </el-menu-item>
        <el-menu-item index="/fences">
          <el-icon><Location /></el-icon>
          <span>电子围栏</span>
        </el-menu-item>
        <el-menu-item index="/jobs">
          <el-icon><Notebook /></el-icon>
          <span>作业计划</span>
        </el-menu-item>
        <el-menu-item index="/alarms">
          <el-icon><Warning /></el-icon>
          <span>告警管理</span>
        </el-menu-item>
        <el-sub-menu index="/system">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统管理</span>
          </template>
          <el-menu-item index="/system/users">用户管理</el-menu-item>
          <el-menu-item index="/system/roles">角色管理</el-menu-item>
          <el-menu-item index="/system/departments">部门管理</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="title">{{ (route.meta.title as string) || "控制台" }}</span>
        <div class="user">
          <span class="nickname">{{ nickname }}</span>
          <el-button text type="primary" @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #001529;
  color: #fff;
}
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  color: #fff;
}
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
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #eee;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.user {
  display: flex;
  align-items: center;
  gap: 12px;
}
.nickname {
  color: #606266;
}
.main {
  background: #f0f2f5;
}
</style>
