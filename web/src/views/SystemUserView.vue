<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { createUser, deleteUser, listUsers, updateUser } from "@/api/user";
import { listRoles } from "@/api/role";
import { fetchDepartments } from "@/api/department";
import { useAuthStore } from "@/stores/auth";
import type { Department, Role, SysUser } from "@/types";

const auth = useAuthStore();
const loading = ref(false);
const users = ref<SysUser[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);
const keyword = ref("");

const roles = ref<Role[]>([]);
const depts = ref<Department[]>([]);

const roleMap = computed(() => {
  const m: Record<string, string> = {};
  roles.value.forEach((r) => (m[r.code] = r.name));
  return m;
});
const deptMap = computed(() => {
  const m: Record<number, string> = {};
  depts.value.forEach((d) => (m[d.id] = d.name));
  return m;
});
const roleOptions = computed(() =>
  roles.value.map((r) => ({ label: r.name, value: r.code })),
);
const deptOptions = computed(() => [
  { label: "（无）", value: 0 },
  ...depts.value.map((d) => ({ label: d.name, value: d.id })),
]);

const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const submitting = ref(false);
const form = reactive({
  id: undefined as number | undefined,
  username: "",
  password: "",
  nickname: "",
  email: "",
  phone: "",
  dept_id: null as number | null,
  role_codes: [] as string[],
  status: true,
});

function resetForm() {
  form.id = undefined;
  form.username = "";
  form.password = "";
  form.nickname = "";
  form.email = "";
  form.phone = "";
  form.dept_id = null;
  form.role_codes = [];
  form.status = true;
}

async function loadUsers() {
  loading.value = true;
  try {
    const r = await listUsers({
      keyword: keyword.value || undefined,
      page: page.value,
      size: size.value,
    });
    users.value = r.items;
    total.value = r.total;
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  dialogMode.value = "create";
  resetForm();
  dialogVisible.value = true;
}
function openEdit(row: SysUser) {
  dialogMode.value = "edit";
  resetForm();
  form.id = row.id;
  form.username = row.username;
  form.nickname = row.nickname || "";
  form.email = row.email || "";
  form.phone = row.phone || "";
  form.dept_id = row.dept_id;
  form.role_codes = [...row.roles];
  form.status = row.status;
  dialogVisible.value = true;
}

async function submit() {
  if (dialogMode.value === "create" && !form.password) {
    ElMessage.error("请输入初始密码");
    return;
  }
  submitting.value = true;
  try {
    if (dialogMode.value === "create") {
      await createUser({
        username: form.username,
        password: form.password,
        nickname: form.nickname || null,
        email: form.email || null,
        phone: form.phone || null,
        dept_id: form.dept_id || null,
        role_codes: form.role_codes,
        status: form.status,
      });
      ElMessage.success("用户创建成功");
    } else {
      const data: Record<string, unknown> = {
        nickname: form.nickname || null,
        email: form.email || null,
        phone: form.phone || null,
        dept_id: form.dept_id || null,
        status: form.status,
        role_codes: form.role_codes,
      };
      if (form.password) data.password = form.password;
      await updateUser(form.id!, data as never);
      ElMessage.success("用户更新成功");
    }
    dialogVisible.value = false;
    loadUsers();
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false;
  }
}

async function remove(row: SysUser) {
  try {
    await ElMessageBox.confirm(
      `确认删除用户「${row.username}」？`,
      "提示",
      { type: "warning" },
    );
  } catch {
    return;
  }
  try {
    await deleteUser(row.id);
    ElMessage.success("已删除");
    loadUsers();
  } catch {
    // 拦截器提示
  }
}

function onSearch() {
  page.value = 1;
  loadUsers();
}
function onPageChange(p: number) {
  page.value = p;
  loadUsers();
}

async function loadRoles() {
  roles.value = await listRoles();
}
async function loadDepartments() {
  depts.value = await fetchDepartments();
}

onMounted(async () => {
  await Promise.all([loadRoles(), loadDepartments()]);
  loadUsers();
});
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索账号/昵称"
        clearable
        style="width: 220px"
        @keyup.enter="onSearch"
      />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button
        v-if="auth.hasPermission('user:add')"
        type="success"
        @click="openCreate"
        >新建用户</el-button
      >
    </div>

    <el-table v-loading="loading" :data="users" border stripe>
      <el-table-column prop="username" label="账号" width="140" />
      <el-table-column prop="nickname" label="昵称" width="140" />
      <el-table-column label="角色" min-width="180">
        <template #default="{ row }">
          <el-tag
            v-for="c in row.roles"
            :key="c"
            size="small"
            style="margin-right: 4px"
            >{{ roleMap[c] || c }}</el-tag
          >
        </template>
      </el-table-column>
      <el-table-column label="部门" width="140">
        <template #default="{ row }">
          {{ row.dept_id != null ? deptMap[row.dept_id] || "—" : "—" }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status ? 'success' : 'info'" size="small">
            {{ row.status ? "启用" : "禁用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="{ row }">
          {{ row.created_at ? row.created_at.replace("T", " ").slice(0, 19) : "—" }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="auth.hasPermission('user:edit')"
            link
            type="primary"
            @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="auth.hasPermission('user:delete') && !row.is_superuser"
            link
            type="danger"
            @click="remove(row)"
            >删除</el-button
          >
          <span
            v-if="row.is_superuser"
            style="color: #909399; font-size: 12px"
            >内置保护</span
          >
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        background
        layout="total,prev,pager,next"
        :total="total"
        :page-size="size"
        :current-page="page"
        @current-change="onPageChange"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建用户' : '编辑用户'"
      width="480px"
    >
      <el-form :model="form" label-width="80px">
        <el-form-item label="账号">
          <el-input v-model="form.username" :disabled="dialogMode === 'edit'" />
        </el-form-item>
        <el-form-item :label="dialogMode === 'create' ? '初始密码' : '重置密码'">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="dialogMode === 'edit' ? '留空则不修改' : '请输入密码'"
            show-password
          />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="form.nickname" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="归属部门">
          <el-select
            v-model="form.dept_id"
            placeholder="请选择"
            clearable
            style="width: 100%"
          >
            <el-option
              v-for="o in deptOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select
            v-model="form.role_codes"
            multiple
            placeholder="请选择"
            style="width: 100%"
          >
            <el-option
              v-for="o in roleOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit"
          >确定</el-button
        >
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 4px;
}
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.pager {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
</style>
