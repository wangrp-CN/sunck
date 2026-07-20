<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  createDepartment,
  deleteDepartment,
  fetchDepartments,
  updateDepartment,
} from "@/api/department";
import { useAuthStore } from "@/stores/auth";
import type { Department } from "@/types";

const auth = useAuthStore();
const loading = ref(false);
const depts = ref<Department[]>([]);

const deptMap = computed(() => {
  const m: Record<number, string> = {};
  depts.value.forEach((d) => (m[d.id] = d.name));
  return m;
});
const deptOptions = computed(() => [
  { label: "（根 / 无上级）", value: 0 },
  ...depts.value.map((d) => ({ label: d.name, value: d.id })),
]);

const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const submitting = ref(false);
const form = reactive({
  id: undefined as number | undefined,
  name: "",
  code: "",
  parent_id: null as number | null,
  leader: "",
  phone: "",
  sort: 1,
  status: true,
  remark: "",
});
function resetForm() {
  form.id = undefined;
  form.name = "";
  form.code = "";
  form.parent_id = null;
  form.leader = "";
  form.phone = "";
  form.sort = 1;
  form.status = true;
  form.remark = "";
}
function openCreate() {
  dialogMode.value = "create";
  resetForm();
  dialogVisible.value = true;
}
function openEdit(row: Department) {
  dialogMode.value = "edit";
  resetForm();
  form.id = row.id;
  form.name = row.name;
  form.code = row.code;
  form.parent_id = row.parent_id;
  form.leader = row.leader || "";
  form.phone = row.phone || "";
  form.sort = row.sort;
  form.status = row.status;
  form.remark = row.remark || "";
  dialogVisible.value = true;
}
async function submit() {
  submitting.value = true;
  try {
    const data = {
      name: form.name,
      code: form.code,
      parent_id: form.parent_id || null,
      leader: form.leader || null,
      phone: form.phone || null,
      sort: form.sort,
      status: form.status,
      remark: form.remark || null,
    };
    if (dialogMode.value === "create") {
      await createDepartment(data);
      ElMessage.success("部门创建成功");
    } else {
      await updateDepartment(form.id!, data);
      ElMessage.success("部门更新成功");
    }
    dialogVisible.value = false;
    loadDepartments();
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false;
  }
}
async function remove(row: Department) {
  try {
    await ElMessageBox.confirm(`确认删除部门「${row.name}」？`, "提示", {
      type: "warning",
    });
  } catch {
    return;
  }
  try {
    await deleteDepartment(row.id);
    ElMessage.success("已删除");
    loadDepartments();
  } catch {
    // 拦截器提示
  }
}
async function loadDepartments() {
  loading.value = true;
  try {
    depts.value = await fetchDepartments();
  } finally {
    loading.value = false;
  }
}
onMounted(loadDepartments);
</script>

<template>
  <div class="page">
    <div class="tool-bar">
      <el-button
        v-if="auth.hasPermission('dept:add')"
        type="success"
        @click="openCreate"
        >新建部门</el-button
      >
    </div>

    <el-table v-loading="loading" :data="depts" border stripe row-key="id">
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="code" label="编码" width="160" />
      <el-table-column label="上级" width="160">
        <template #default="{ row }">
          {{ row.parent_id != null ? deptMap[row.parent_id] || "—" : "（根）" }}
        </template>
      </el-table-column>
      <el-table-column prop="leader" label="负责人" width="120" />
      <el-table-column prop="phone" label="电话" width="140" />
      <el-table-column prop="sort" label="排序" width="80" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status ? 'success' : 'info'" size="small">
            {{ row.status ? "启用" : "禁用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="auth.hasPermission('dept:edit')"
            link
            type="primary"
            @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="auth.hasPermission('dept:delete')"
            link
            type="danger"
            @click="remove(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建部门' : '编辑部门'"
      width="460px"
    >
      <el-form :model="form" label-width="80px">
        <el-form-item label="部门名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="部门编码">
          <el-input v-model="form.code" :disabled="dialogMode === 'edit'" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-select
            v-model="form.parent_id"
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
        <el-form-item label="负责人">
          <el-input v-model="form.leader" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" />
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
  </div>
</template>

<style scoped>
.page {
  padding: 4px;
}
.tool-bar {
  margin-bottom: 14px;
}
</style>
