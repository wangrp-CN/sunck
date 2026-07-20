<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createProject,
  deleteProject,
  fetchProjects,
  updateProject,
} from "@/api/project";
import { fetchDepartments } from "@/api/department";
import type { Department, Project, ProjectCreate, ProjectStatus, ProjectUpdate } from "@/types";

const auth = useAuthStore();

// 权限门控（后端仍会二次校验）
const canAdd = computed(() => auth.user?.permission_codes.includes("project:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("project:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("project:delete") ?? false);

const loading = ref(false);
const keyword = ref("");
const tableData = ref<Project[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

// 部门字典：id -> name
const deptMap = ref<Map<number, string>>(new Map());

const statusTagType: Record<ProjectStatus, "" | "success" | "warning" | "info"> = {
  在建: "success",
  停工: "warning",
  竣工: "info",
};

async function loadDepartments() {
  try {
    const depts = await fetchDepartments();
    const map = new Map<number, string>();
    depts.forEach((d: Department) => map.set(d.id, d.name));
    deptMap.value = map;
  } catch {
    // 部门加载失败不阻断列表，仅 dept 名称显示为原始 ID
  }
}

function deptName(id: number | null): string {
  if (id == null) return "—";
  return deptMap.value.get(id) ?? `ID:${id}`;
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchProjects({ keyword: keyword.value || undefined, page: page.value, size: size.value });
    tableData.value = pageData.items;
    total.value = pageData.total;
  } catch {
    // 拦截器已统一提示
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.value = 1;
  loadData();
}

function handleReset() {
  keyword.value = "";
  page.value = 1;
  loadData();
}

function handlePageChange(p: number) {
  page.value = p;
  loadData();
}

// ---- 新增/编辑弹窗 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();

const emptyForm = () => ({
  name: "",
  short_name: "",
  dept_id: undefined as number | undefined,
  status: "在建" as ProjectStatus,
  section: "",
  mileage: "",
  coordinate: "",
  duration: undefined as number | undefined,
  start_date: "" as string | null,
  end_date: "" as string | null,
  intro: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  name: [{ required: true, message: "请输入项目名称", trigger: "blur" }],
  dept_id: [{ required: true, message: "请选择归属部门", trigger: "change" }],
  status: [{ required: true, message: "请选择状态", trigger: "change" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm());
  dialogVisible.value = true;
}

async function openEdit(row: Project) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    name: row.name,
    short_name: row.short_name ?? "",
    dept_id: row.dept_id ?? undefined,
    status: row.status,
    section: row.section ?? "",
    mileage: row.mileage ?? "",
    coordinate: row.coordinate ?? "",
    duration: row.duration ?? undefined,
    start_date: row.start_date,
    end_date: row.end_date,
    intro: row.intro ?? "",
  });
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      // 构造请求体：空字符串字段转 null，保持与后端 Schema 一致
      const payload: ProjectCreate | ProjectUpdate = {
        name: form.name,
        dept_id: form.dept_id as number,
        short_name: form.short_name ? form.short_name : null,
        status: form.status,
        section: form.section ? form.section : null,
        mileage: form.mileage ? form.mileage : null,
        coordinate: form.coordinate ? form.coordinate : null,
        duration: form.duration ?? null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        intro: form.intro ? form.intro : null,
      };
      if (dialogMode.value === "create") {
        await createProject(payload as ProjectCreate);
        ElMessage.success("项目创建成功");
      } else {
        await updateProject(editingId.value as number, payload as ProjectUpdate);
        ElMessage.success("项目更新成功");
      }
      dialogVisible.value = false;
      loadData();
    } catch {
      // 拦截器已统一提示
    } finally {
      submitting.value = false;
    }
  });
}

async function handleDelete(row: Project) {
  try {
    await ElMessageBox.confirm(`确定删除项目「${row.name}」吗？该操作将软删项目。`, "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await deleteProject(row.id);
    ElMessage.success("项目已删除");
    loadData();
  } catch {
    // 拦截器已统一提示
  }
}

onMounted(async () => {
  // 刷新后直接进入本页时，auth.user 可能尚未加载（权限门控需要），
  // 这里兜底拉取一次，失败由拦截器统一处理。
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      // 拦截器已处理
    }
  }
  loadDepartments();
  loadData();
});
</script>

<template>
  <div class="project-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按项目名称搜索"
        clearable
        class="search-input"
        @keyup.enter="handleSearch"
        @clear="handleReset"
      />
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增项目</el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="loading" :data="tableData" border stripe class="table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="项目名称" min-width="160" show-overflow-tooltip />
      <el-table-column prop="short_name" label="简称" width="120" show-overflow-tooltip />
      <el-table-column label="归属部门" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ deptName(row.dept_id) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status as ProjectStatus]">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="section" label="区间" width="140" show-overflow-tooltip />
      <el-table-column prop="mileage" label="里程" width="120" show-overflow-tooltip />
      <el-table-column prop="start_date" label="开工" width="120" />
      <el-table-column prop="end_date" label="完工" width="120" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canDelete" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增项目' : '编辑项目'"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="简称" prop="short_name">
          <el-input v-model="form.short_name" placeholder="项目简称（可选）" />
        </el-form-item>
        <el-form-item label="归属部门" prop="dept_id">
          <el-select v-model="form.dept_id" placeholder="请选择部门" class="full">
            <el-option
              v-for="[id, name] in deptMap"
              :key="id"
              :label="name"
              :value="id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-select v-model="form.status" class="full">
            <el-option label="在建" value="在建" />
            <el-option label="停工" value="停工" />
            <el-option label="竣工" value="竣工" />
          </el-select>
        </el-form-item>
        <el-form-item label="区间">
          <el-input v-model="form.section" placeholder="如：K12+300~K15+800" />
        </el-form-item>
        <el-form-item label="里程">
          <el-input v-model="form.mileage" placeholder="如：3.5km" />
        </el-form-item>
        <el-form-item label="坐标">
          <el-input v-model="form.coordinate" placeholder="如：120.123,30.456" />
        </el-form-item>
        <el-form-item label="工期(天)">
          <el-input-number v-model="form.duration" :min="0" :controls="false" class="full" />
        </el-form-item>
        <el-form-item label="开工日期">
          <el-date-picker
            v-model="form.start_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
        <el-form-item label="完工日期">
          <el-date-picker
            v-model="form.end_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
          />
        </el-form-item>
        <el-form-item label="项目介绍">
          <el-input v-model="form.intro" type="textarea" :rows="3" placeholder="项目介绍（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.project-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.search-input {
  width: 240px;
}
.full {
  width: 100%;
}
.table {
  width: 100%;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
