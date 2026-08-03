<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules, ElMessage, ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createProject,
  deleteProject,
  fetchProjects,
  updateProject,
} from "@/api/project";
import { fetchDepartmentTree, fetchDepartments } from "@/api/department";
import type {
  Department,
  DepartmentTree,
  Project,
  ProjectCreate,
  ProjectListParams,
  ProjectStatus,
  ProjectUpdate,
} from "@/types";

const auth = useAuthStore();

// 权限门控（后端仍会二次校验）
const canAdd = computed(() => auth.user?.permission_codes.includes("project:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("project:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("project:delete") ?? false);

const loading = ref(false);
const tableData = ref<Project[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

// 部门字典：id -> name（列表单元格展示归属部门名称）
const deptMap = ref<Map<number, string>>(new Map());
// 部门树（查询区与弹窗的归属部门下拉）
const deptTree = ref<DepartmentTree[]>([]);

// 项目状态标签色彩：在建=蓝、竣工=绿、停工=红（对齐原型）
const statusTagType: Record<ProjectStatus, "primary" | "success" | "danger"> = {
  在建: "primary",
  竣工: "success",
  停工: "danger",
};

// ---- 查询条件 ----
const query = reactive({
  name: "",
  dept_id: null as number | null,
  start_date_range: null as [string, string] | null,
  end_date_range: null as [string, string] | null,
  status: null as ProjectStatus | null,
});

async function loadDepartments() {
  try {
    const [depts, tree] = await Promise.all([fetchDepartments(), fetchDepartmentTree()]);
    const map = new Map<number, string>();
    depts.forEach((d: Department) => map.set(d.id, d.name));
    deptMap.value = map;
    deptTree.value = tree;
  } catch {
    // 部门加载失败不阻断列表
  }
}

function deptName(id: number | null): string {
  if (id == null) return "—";
  return deptMap.value.get(id) ?? `ID:${id}`;
}

function buildParams(): ProjectListParams {
  return {
    name: query.name || undefined,
    dept_id: query.dept_id || undefined,
    start_date_from: query.start_date_range?.[0] || undefined,
    start_date_to: query.start_date_range?.[1] || undefined,
    end_date_from: query.end_date_range?.[0] || undefined,
    end_date_to: query.end_date_range?.[1] || undefined,
    status: query.status || undefined,
    page: page.value,
    size: size.value,
  };
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchProjects(buildParams());
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
  query.name = "";
  query.dept_id = null;
  query.start_date_range = null;
  query.end_date_range = null;
  query.status = null;
  page.value = 1;
  loadData();
}

function handlePageChange(p: number) {
  page.value = p;
  loadData();
}

// ---- 新增 / 编辑 / 查看 弹窗 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit" | "view">("create");
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
  lng: "",
  lat: "",
  start_date: "" as string | null,
  end_date: "" as string | null,
  intro: "",
});

const form = reactive(emptyForm());

// 工期只读：由开工 / 完工日期计算
const computedDuration = computed<number | null>(() => {
  if (!form.start_date || !form.end_date) return null;
  const s = new Date(form.start_date).getTime();
  const e = new Date(form.end_date).getTime();
  if (Number.isNaN(s) || Number.isNaN(e)) return null;
  const days = Math.round((e - s) / 86400000);
  return days >= 0 ? days : null;
});

const isView = computed(() => dialogMode.value === "view");

const rules: FormRules = {
  name: [{ required: true, message: "请输入项目名称", trigger: "blur" }],
  dept_id: [{ required: true, message: "请选择归属部门", trigger: "change" }],
  short_name: [{ required: true, message: "请输入项目简称", trigger: "blur" }],
  intro: [{ required: true, message: "请输入项目介绍", trigger: "blur" }],
};

function parseCoord(c?: string | null): { lng: string; lat: string } {
  if (!c || !c.includes(",")) return { lng: "", lat: "" };
  const [lng, lat] = c.split(",");
  return { lng: (lng ?? "").trim(), lat: (lat ?? "").trim() };
}

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm());
  dialogVisible.value = true;
}

function openEdit(row: Project) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, emptyForm(), {
    name: row.name,
    short_name: row.short_name ?? "",
    dept_id: row.dept_id ?? undefined,
    status: row.status,
    section: row.section ?? "",
    mileage: row.mileage ?? "",
    intro: row.intro ?? "",
    start_date: row.start_date,
    end_date: row.end_date,
    ...parseCoord(row.coordinate),
  });
  dialogVisible.value = true;
}

function openView(row: Project) {
  dialogMode.value = "view";
  editingId.value = row.id;
  Object.assign(form, emptyForm(), {
    name: row.name,
    short_name: row.short_name ?? "",
    dept_id: row.dept_id ?? undefined,
    status: row.status,
    section: row.section ?? "",
    mileage: row.mileage ?? "",
    intro: row.intro ?? "",
    start_date: row.start_date,
    end_date: row.end_date,
    ...parseCoord(row.coordinate),
  });
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const coord =
        form.lng.trim() && form.lat.trim()
          ? `${form.lng.trim()},${form.lat.trim()}`
          : null;
      // 工期由服务端按起止日期计算，前端不传 duration
      const payload: ProjectCreate | ProjectUpdate = {
        name: form.name,
        dept_id: form.dept_id as number,
        short_name: form.short_name ? form.short_name : null,
        intro: form.intro ? form.intro : null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        mileage: form.mileage ? form.mileage : null,
        section: form.section ? form.section : null,
        coordinate: coord,
        status: form.status,
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
    await ElMessageBox.confirm("您确认删除当前项目？", "删除确认", {
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
  <div class="project-list-page">
    <!-- 查询区 -->
    <div class="toolbar">
      <el-tree-select
        v-model="query.dept_id"
        :data="deptTree"
        :props="{ value: 'id', label: 'name', children: 'children' }"
        node-key="id"
        :check-strictly="true"
        filterable
        clearable
        placeholder="归属部门"
        class="w-200"
      />
      <el-input v-model="query.name" placeholder="项目名称" clearable class="w-180" />
      <el-date-picker
        v-model="query.start_date_range"
        type="daterange"
        range-separator="~"
        start-placeholder="开工起"
        end-placeholder="开工止"
        value-format="YYYY-MM-DD"
        class="w-260"
      />
      <el-date-picker
        v-model="query.end_date_range"
        type="daterange"
        range-separator="~"
        start-placeholder="完工起"
        end-placeholder="完工止"
        value-format="YYYY-MM-DD"
        class="w-260"
      />
      <el-select v-model="query.status" placeholder="项目状态" clearable class="w-140">
        <el-option label="在建" value="在建" />
        <el-option label="停工" value="停工" />
        <el-option label="竣工" value="竣工" />
      </el-select>
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增</el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="loading" :data="tableData" border stripe class="table">
      <el-table-column label="序号" width="64" align="center">
        <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
      </el-table-column>
      <el-table-column label="归属部门" width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ deptName(row.dept_id) }}</template>
      </el-table-column>
      <el-table-column prop="name" label="项目名称" min-width="160" show-overflow-tooltip />
      <el-table-column prop="short_name" label="项目简称" width="120" show-overflow-tooltip />
      <el-table-column prop="intro" label="项目介绍" min-width="200" show-overflow-tooltip />
      <el-table-column prop="start_date" label="开工日期" width="120" />
      <el-table-column prop="end_date" label="完工日期" width="120" />
      <el-table-column label="项目工期" width="100" align="center">
        <template #default="{ row }">{{ row.duration != null ? row.duration + " 天" : "—" }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" show-overflow-tooltip />
      <el-table-column label="项目状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType[row.status as ProjectStatus]" effect="light">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="info" @click="openView(row)">查看</el-button>
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

    <!-- 新增 / 编辑 / 查看 弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增项目' : dialogMode === 'edit' ? '编辑项目' : '项目详情'"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px" :disabled="isView">
        <el-form-item label="归属部门" prop="dept_id">
          <el-tree-select
            v-model="form.dept_id"
            :data="deptTree"
            :props="{ value: 'id', label: 'name', children: 'children' }"
            node-key="id"
            :check-strictly="true"
            filterable
            clearable
            placeholder="请选择部门"
            class="full"
          />
        </el-form-item>
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入项目名称" />
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
        <el-form-item label="项目介绍" prop="intro">
          <el-input v-model="form.intro" type="textarea" :rows="3" placeholder="项目介绍（必填）" />
        </el-form-item>
        <el-form-item label="项目简称" prop="short_name">
          <el-input v-model="form.short_name" placeholder="项目简称（必填）" />
        </el-form-item>
        <el-form-item label="里程">
          <el-input v-model="form.mileage" placeholder="如：3.5km" />
        </el-form-item>
        <el-form-item label="区间">
          <el-input v-model="form.section" placeholder="如：K12+300~K15+800" />
        </el-form-item>
        <el-form-item label="经度">
          <el-input v-model="form.lng" placeholder="如：116.397" />
        </el-form-item>
        <el-form-item label="项目工期">
          <el-input
            :model-value="computedDuration != null ? computedDuration + ' 天' : '—'"
            disabled
            placeholder="由开工/完工日期自动计算"
            class="full"
          />
        </el-form-item>
        <el-form-item label="项目状态">
          <el-select v-model="form.status" class="full" :disabled="isView">
            <el-option label="在建" value="在建" />
            <el-option label="停工" value="停工" />
            <el-option label="竣工" value="竣工" />
          </el-select>
        </el-form-item>
        <el-form-item label="纬度">
          <el-input v-model="form.lat" placeholder="如：39.909" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ isView ? "关闭" : "取消" }}</el-button>
        <el-button v-if="!isView" type="primary" :loading="submitting" @click="handleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.project-list-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.w-140 {
  width: 140px;
}
.w-180 {
  width: 180px;
}
.w-200 {
  width: 200px;
}
.w-260 {
  width: 260px;
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
