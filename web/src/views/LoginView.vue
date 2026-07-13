<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import type { LoginRequest } from "@/types";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const form = reactive<LoginRequest>({
  username: "",
  password: "",
  captcha: undefined,
  captcha_key: undefined,
});

const loading = ref(false);

async function handleSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  loading.value = true;
  try {
    await auth.login(form);
    ElMessage.success("登录成功");
    const redirect = (route.query.redirect as string) || "/dashboard";
    router.push(redirect);
  } catch {
    // 错误已在拦截器统一提示
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <div class="card-header">涉铁工程智能监控平台</div>
      </template>
      <el-form :model="form" label-position="top" @submit.prevent="handleSubmit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" clearable />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            show-password
            @keyup.enter="handleSubmit"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" style="width: 100%" @click="handleSubmit">
            登 录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="hint">默认管理员：admin / Admin@123456</div>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1890ff 0%, #001529 100%);
}
.login-card {
  width: 380px;
}
.card-header {
  text-align: center;
  font-size: 18px;
  font-weight: 700;
}
.hint {
  text-align: center;
  color: #909399;
  font-size: 12px;
}
</style>
