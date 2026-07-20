<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { Loading } from "@element-plus/icons-vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { getCaptcha } from "@/api/auth";
import type { LoginRequest } from "@/types";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const form = reactive<LoginRequest>({
  username: "",
  password: "",
  captcha: "",
  captcha_key: "",
});

const loading = ref(false);
const captchaImage = ref("");
const captchaLoading = ref(false);
const captchaError = ref(false);

async function refreshCaptcha() {
  if (captchaLoading.value) return;
  captchaLoading.value = true;
  captchaError.value = false;
  try {
    const data = await getCaptcha();
    form.captcha_key = data.captcha_key;
    captchaImage.value = data.captcha_image;
    form.captcha = "";
  } catch (error) {
    captchaError.value = true;
    ElMessage.error("验证码加载失败，请点击图片重试");
    // eslint-disable-next-line no-console
    console.error("[captcha] load failed", error);
  } finally {
    captchaLoading.value = false;
  }
}

function handleCaptchaError() {
  captchaError.value = true;
  ElMessage.error("验证码图片无法显示，请点击刷新");
}

async function handleSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  if (!form.captcha || !form.captcha_key) {
    ElMessage.warning("请输入验证码");
    return;
  }
  loading.value = true;
  try {
    await auth.login(form);
    ElMessage.success("登录成功");
  } catch {
    // 登录失败（账号/验证码错误、账户锁定等）已在拦截器统一提示；
    // 刷新验证码避免重放爆破，并停留在登录页。
    await refreshCaptcha();
    return;
  } finally {
    loading.value = false;
  }
  // 登录成功（token 已持久化）后跳转；即便 loadProfile 偶发失败，
  // 也不影响进入系统（DashboardView.onMounted 会兜底重载用户信息）。
  const redirect = (route.query.redirect as string) || "/dashboard";
  router.push(redirect);
}

onMounted(() => {
  // 页面加载时自动拉取验证码
  void refreshCaptcha();
});
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
        <el-form-item label="验证码" class="captcha-item">
          <div class="captcha-row">
            <el-input
              v-model="form.captcha"
              placeholder="请输入验证码"
              maxlength="6"
              class="captcha-input"
              @keyup.enter="handleSubmit"
            />
            <div class="captcha-image-wrap" title="点击刷新验证码" @click="refreshCaptcha">
              <el-image
                v-if="captchaImage && !captchaError"
                :src="captchaImage"
                fit="fill"
                class="captcha-image"
                @error="handleCaptchaError"
              />
              <div v-else class="captcha-placeholder">
                <el-icon v-if="captchaLoading" class="is-loading"><Loading /></el-icon>
                <span v-else>点击刷新</span>
              </div>
            </div>
          </div>
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
.captcha-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}
.captcha-input {
  flex: 1;
}
.captcha-image-wrap {
  width: 120px;
  height: 40px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
  cursor: pointer;
  flex-shrink: 0;
  background-color: #f5f7fa;
  display: flex;
  align-items: center;
  justify-content: center;
}
.captcha-image-wrap:hover {
  border-color: #409eff;
}
.captcha-image {
  width: 100%;
  height: 100%;
  display: block;
}
.captcha-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 12px;
  user-select: none;
}
.hint {
  text-align: center;
  color: #909399;
  font-size: 12px;
}
</style>
