<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  assignRoleDepartments,
  assignRolePermissions,
  createRole,
  deleteRole,
  listRoles,
  updateRole,
} from "@/api/role";
import { listPermissions } from "@/api/permission";
import { fetchDepartments } from "@/api/department";
import { useAuthStore } from "@/stores/auth";
import type { Department, Permission, Role } from "@/types";

const auth = useAuthStore();
const loading = ref(false);
const roles = ref<Role[]>([]);
const permissions = ref<Permission[]>([]);
const depts = ref<Department[]>([]);

const SCOPE_LABELS: Record<number, string> = {
  1: "全部",
  2: "自定义部门",
  3: "本部门及以下",
  4: "仅本人",
};

const modules = computed(() => permissions.value.filter((p) => p.type === 1));
function childrenOf(pid: number): Permission[] {
  return permissions.value.filter((p) => p.parent_id === pid);
}
const deptOptions = computed(() => [
  { label: "（无）", value: 0 },
  ...depts.value.map((d) => ({ label: d.name, value: d.id })),
]);

// 新建/编辑
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const submitting = ref(false);
const form = reactive({
  id: undefined as number | undefined,
  name: "",
  code: "",
  data_scope: 4,
  remark: "",
  status: true,
});
function resetForm() {
  form.id = undefined;
  form.name = "";
  form.code = "";
  form.data_scope = 4;
  form.remark = "";
  form.status = true;
}
function openCreate() {
  dialogMode.value = "create";
  resetForm();
  dialogVisible.value = true;
}
function openEdit(row: Role) {
  dialogMode.value = "edit";
  resetForm();
  form.id = row.id;
  form.name = row.name;
  form.code = row.code;
  form.data_scope = row.data_scope;
  form.remark = row.remark || "";
  form.status = row.status;
  dialogVisible.value = true;
}
async function submit() {
  submitting.value = true;
  try {
    if (dialogMode.value === "create") {
      await createRole({
        name: form.name,
        code: form.code,
        data_scope: form.data_scope,
        remark: form.remark || null,
      });
      ElMessage.success("角色创建成功");
    } else {
      await updateRole(form.id!, {
        name: form.name,
        data_scope: form.data_scope,
        remark: form.remark || null,
        status: form.status,
      });
      ElMessage.success("角色更新成功");
    }
    dialogVisible.value = false;
    loadRoles();
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false;
  }
}

// 分配权限
const permDialog = ref(false);
const permRole = ref<Role | null>(null);
const selectedCodes = ref<string[]>([]);
function openPerm(row: Role) {
  permRole.value = row;
  selectedCodes.value = [...row.permission_codes];
  permDialog.value = true;
}
async function savePerm() {
  if (!permRole.value) return;
  submitting.value = true;
  try {
    await assignRolePermissions(permRole.value.id, selectedCodes.value);
    ElMessage.success("权限已分配");
    permDialog.value = false;
    loadRoles();
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false;
  }
}

// 分配部门
const deptDialog = ref(false);
const deptRole = ref<Role | null>(null);
const selectedDepts = ref<number[]>([]);
function openDept(row: Role) {
  deptRole.value = row;
  selectedDepts.value = [...row.dept_ids];
  deptDialog.value = true;
}
async function saveDept() {
  if (!deptRole.value) return;
  submitting.value = true;
  try {
    await assignRoleDepartments(deptRole.value.id, selectedDepts.value);
    ElMessage.success("数据范围部门已保存");
    deptDialog.value = false;
    loadRoles();
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false;
  }
}

async function remove(row: Role) {
  if (row.is_system) return;
  try {
    await ElMessageBox.confirm(`确认删除角色「${row.name}」？`, "提示", {
      type: "warning",
    });
  } catch {
    return;
  }
  try {
    await deleteRole(row.id);
    ElMessage.success("已删除");
    loadRoles();
  } catch {
    // 拦截器提示
  }
}

async function loadRoles() {
  loading.value = true;
  try {
    roles.value = await listRoles();
  } finally {
    loading.value = false;
  }
}
async function loadPermissions() {
  permissions.value = await listPermissions();
}
async function loadDepartments() {
  depts.value = await fetchDepartments();
}

onMounted(async () => {
  await Promise.all([loadPermissions(), loadDepartments()]);
  loadRoles();
});
</script>

<template>
  <div class="page">
    <div class="tool-bar">
      <el-button
        v-if="auth.hasPermission('role:add')"
        type="success"
        @click="openCreate"
        >新建角色</el-button
      >
    </div>

    <el-table v-loading="loading" :data="roles" border stripe>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="code" label="编码" width="160" />
      <el-table-column label="数据范围" width="130">
        <template #default="{ row }">
          <el-tag size="small">{{ SCOPE_LABELS[row.data_scope] || row.data_scope }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="系统内置" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.is_system" type="warning" size="small">内置</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status ? 'success' : 'info'" size="small">
            {{ row.status ? "启用" : "禁用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="权限数" width="80">
        <template #default="{ row }">{{ row.permission_codes.length }}</template>
      </el-table-column>
      <el-table-column label="操作" min-width="260" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="auth.hasPermission('role:edit')"
            link
            type="primary"
            @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="auth.hasPermission('role:assign')"
            link
            type="primary"
            @click="openPerm(row)"
            >分配权限</el-button
          >
          <el-button
            v-if="auth.hasPermission('role:assign')"
            link
            type="primary"
            :disabled="row.data_scope !== 2"
            @click="openDept(row)"
            >数据范围</el-button
          >
          <el-button
            v-if="auth.hasPermission('role:delete') && !row.is_system"
            link
            type="danger"
            @click="remove(row)"
            >删除</el-button
          >
          <span v-if="row.is_system" style="font-size: 12px; color: #909399">内置保护</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建角色' : '编辑角色'"
      width="460px"
    >
      <el-form :model="form" label-width="88px">
        <el-form-item label="角色名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="角色编码">
          <el-input
            v-model="form.code"
            :disabled="dialogMode === 'edit'"
            placeholder="字母数字下划线冒号"
          />
        </el-form-item>
        <el-form-item label="数据范围">
          <el-select v-model="form.data_scope" style="width: 100%">
            <el-option :value="1" label="全部数据" />
            <el-option :value="2" label="自定义部门（含下级）" />
            <el-option :value="3" label="本部门及以下" />
            <el-option :value="4" label="仅本人" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 分配权限 -->
    <el-dialog v-model="permDialog" title="分配权限" width="560px">
      <div class="perm-tree">
        <div v-for="m in modules" :key="m.id" class="perm-module">
          <div class="perm-module-title">{{ m.name }}</div>
          <el-checkbox-group v-model="selectedCodes">
            <el-checkbox
              v-for="c in childrenOf(m.id)"
              :key="c.id"
              :value="c.code"
              :label="c.code"
              border
              class="perm-item"
            >
              {{ c.name }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </div>
      <template #footer>
        <el-button @click="permDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="savePerm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 分配部门 -->
    <el-dialog v-model="deptDialog" title="数据范围（自定义部门）" width="460px">
      <el-alert
        type="info"
        :closable="false"
        style="margin-bottom: 12px"
        >仅 data_scope=2 时生效，所选部门及其全部下级均可见。</el-alert
      >
      <el-select
        v-model="selectedDepts"
        multiple
        placeholder="请选择部门"
        style="width: 100%"
      >
        <el-option
          v-for="o in deptOptions"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
      <template #footer>
        <el-button @click="deptDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="saveDept">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 4px;
}
.tool-bar {
  margin-bottom: 14px;
}
.perm-module {
  margin-bottom: 14px;
}
.perm-module-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: #303133;
}
.perm-item {
  margin-right: 8px;
  margin-bottom: 8px;
}
</style>
