<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(false);

onMounted(async () => {
  if (!auth.user) {
    loading.value = true;
    try {
      await auth.loadProfile();
    } catch {
      // 拦截器已处理
    } finally {
      loading.value = false;
    }
  }
});
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card>
          <template #header>欢迎</template>
          <p>当前用户：{{ auth.user?.nickname || auth.user?.username || "—" }}</p>
          <p>角色：{{ auth.user?.role_codes.join("、") || "—" }}</p>
          <p>权限数：{{ auth.user?.permission_codes.length ?? 0 }}</p>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>数据接入</template>
          <p>MQTT / 设备 / 视频流 模块待接入</p>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>告警概览</template>
          <p>实时告警 / 统计图表待接入</p>
        </el-card>
      </el-col>
    </el-row>
    <el-alert
      class="tip"
      title="骨架提示"
      type="info"
      :closable="false"
      description="这是前端工程骨架：已打通路由守卫、Pinia 状态、Axios(/api 代理到 FastAPI) 与 Element Plus。业务大屏将在后续冲刺中填充。"
    />
  </div>
</template>

<style scoped>
.dashboard {
  padding: 8px;
}
.tip {
  margin-top: 16px;
}
</style>
