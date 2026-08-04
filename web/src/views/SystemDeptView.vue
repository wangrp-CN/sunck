<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  batchDeleteDepartments,
  createDepartment,
  deleteDepartment,
  fetchDepartments,
  fetchDepartmentsPage,
  updateDepartment,
} from "@/api/department";
import TablePager from "@/components/TablePager.vue";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import { useAuthStore } from "@/stores/auth";
import type { Department } from "@/types";

const auth = useAuthStore();
const canDelete = computed(() => auth.hasPermission("dept:delete"));

// 扁平全量（供上级下拉消费，不分页）
const allDepts = ref<Department[]>([]);
// 分页表格
const loading = ref(false);
const tableData = ref<Department[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);
const keyword = ref("");

const deptMap = computed(() => {
  const m: Record<number, string> = {};
  allDepts.value.forEach((d) => (m[d.id] = d.name));
  return m;
});
const deptOptions = computed(() => [
  { label: "（根 / 无上级）", value: 0 },
  ...allDepts.value.map((d) => ({ label: d.name, value: d.id })),
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
    loadTable();
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
    loadTable();
  } catch {
    // 拦截器提示
  }
}
async function loadDepartments() {
  // 扁平全量用于下拉，与表格分页互不影响
  allDepts.value = await fetchDepartments();
}
async function loadTable() {
  loading.value = true;
  try {
    const pageData = await fetchDepartmentsPage({
      page: page.value,
      size: size.value,
      keyword: keyword.value || undefined,
    });
    tableData.value = pageData.items;
    total.value = pageData.total;
  } catch {
    // 拦截器统一提示
  } finally {
    loading.value = false;
  }
}
function handleSearch() {
  page.value = 1;
  loadTable();
}
function handleReset() {
  keyword.value = "";
  page.value = 1;
  loadTable();
}

// ---- 批量选择 / 批量删除（统一交互）----
const {
  tableRef,
  selectedRows,
  batchDeleting,
  onSelectionChange,
  clearSelection,
  onBatchDelete,
} = useBatchSelection({
  deleteApi: batchDeleteDepartments,
  reload: () => loadTable(),
  label: "部门",
});

onMounted(async () => {
  await loadDepartments();
  loadTable();
});
</script>

<template>
  <div class="page">
    <div class="tool-bar">
      <el-input
        v-model="keyword"
        placeholder="按名称/编码搜索"
        clearable
        class="search-input"
        @keyup.enter="handleSearch"
        @clear="handleReset"
      />
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button
        v-if="auth.hasPermission('dept:add')"
        type="success"
        @click="openCreate"
        >新建部门</el-button
      >
    </div>

    <BatchActions
      v-if="canDelete"
      :selected="selectedRows.length"
      :loading="batchDeleting"
      @batch-delete="onBatchDelete"
      @clear="clearSelection"
    />
    <el-table
      v-loading="loading"
      :data="tableData"
      border
      stripe
      row-key="id"
      ref="tableRef"
      @selection-change="onSelectionChange"
    >
      <el-table-column
        v-if="canDelete"
        type="selection"
        width="48"
        :reserve-selection="true"
        fixed="left"
      />
      <el-table-column label="序号" width="64" align="center">
        <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
      </el-table-column>
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

    <div class="pager">
      <TablePager
        v-model:page="page"
        v-model:size="size"
        :total="total"
        :selected="selectedRows.length"
        @change="loadTable"
      />
    </div>

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
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  align-items: center;
}
.search-input {
  width: 220px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
