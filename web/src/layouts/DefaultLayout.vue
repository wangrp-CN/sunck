<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
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
