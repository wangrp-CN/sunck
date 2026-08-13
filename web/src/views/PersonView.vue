<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { type FormInstance, type FormRules } from "element-plus";
import { UserFilled } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import {
  batchDeletePersons,
  createPerson,
  deletePerson,
  fetchPersons,
  updatePerson,
} from "@/api/person";
import { fetchProjects } from "@/api/project";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import type { Person, PersonCreate, PersonUpdate, Project } from "@/types";
import AttachmentManager from "@/components/AttachmentManager.vue";
import TablePager from "@/components/TablePager.vue";

const route = useRoute();
const auth = useAuthStore();
// 读取大屏选中的项目，作为「项目名称」筛选默认值
const projectStore = useProjectStore();

const canAdd = computed(() => auth.hasPermission("person:add"));
const canEdit = computed(() => auth.hasPermission("person:edit"));
const canDelete = computed(() => auth.hasPermission("person:delete"));

// 原型：人员类型下拉可选项（防护人员 / 施工人员 / 管理人员）
const PERSON_TYPES = ["防护人员", "施工人员", "管理人员"];

// 原型：人员图标——多种颜色的工人(戴安全帽)图标，新增/编辑时必选其一
const PERSON_ICONS = [
  { key: "p-red", color: "#F56C6C" },
  { key: "p-orange", color: "#E6A23C" },
  { key: "p-yellow", color: "#F7BA2A" },
  { key: "p-green", color: "#67C23A" },
  { key: "p-blue", color: "#409EFF" },
  { key: "p-purple", color: "#8E71F5" },
  { key: "p-cyan", color: "#13C2C2" },
  { key: "p-gray", color: "#909399" },
];

const loading = ref(false);
const filters = reactive({
  project_id: undefined as number | undefined,
  name: "",
  person_type: "",
});
const tableData = ref<Person[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

const projectMap = ref<Map<number, string>>(new Map());

function projectName(id: number | null): string {
  if (id == null) return "—";
  return projectMap.value.get(id) ?? `ID:${id}`;
}

async function loadProjects() {
  try {
    const all: Project[] = [];
    let p = 1;
    while (p <= 10) {
      const pd = await fetchProjects({ page: p, size: 200 });
      all.push(...pd.items);
      if (all.length >= pd.total) break;
      p++;
    }
    const map = new Map<number, string>();
    all.forEach((pr: Project) => map.set(pr.id, pr.name));
    projectMap.value = map;
  } catch {
    // 不影响列表
  }
}

async function loadData() {
  loading.value = true;
  try {
    const pageData = await fetchPersons({
      project_id: filters.project_id,
      name: filters.name || undefined,
      person_type: filters.person_type || undefined,
      page: page.value,
      size: size.value,
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
  loadData();
}
function handleReset() {
  filters.project_id = undefined;
  filters.name = "";
  filters.person_type = "";
  page.value = 1;
  loadData();
}

// ---- 新增/编辑弹窗 ----
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit">("create");
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();

const emptyForm = () => ({
  project_id: undefined as number | undefined,
  person_no: "",
  name: "",
  gender: "" as string,
  phone: "",
  person_type: "",
  icon: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  // 原型：项目名称默认取列表页选中项目；后端以 project_id 做数据隔离，故仍必填
  project_id: [{ required: true, message: "请选择项目名称", trigger: "change" }],
  person_no: [{ required: true, message: "请输入人员编号", trigger: "blur" }],
  name: [{ required: true, message: "请输入人员姓名", trigger: "blur" }],
  phone: [{ required: true, message: "请输入电话号码", trigger: "blur" }],
  person_type: [{ required: true, message: "请选择人员类型", trigger: "change" }],
  icon: [{ required: true, message: "请选择人员图标", trigger: "change" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  const base = emptyForm();
  // 原型：项目名称默认=列表页选中的项目
  if (filters.project_id != null) base.project_id = filters.project_id;
  Object.assign(form, base);
  dialogVisible.value = true;
}

function openEdit(row: Person) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    project_id: row.project_id ?? undefined,
    person_no: row.person_no,
    name: row.name,
    gender: row.gender ?? "",
    phone: row.phone ?? "",
    person_type: row.person_type ?? "",
    icon: row.icon ?? "",
  });
  dialogVisible.value = true;
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const payload: PersonCreate | PersonUpdate = {
        project_id: form.project_id as number,
        person_no: form.person_no,
        name: form.name,
        gender: form.gender ? form.gender : null,
        phone: form.phone ? form.phone : null,
        person_type: form.person_type ? form.person_type : null,
        icon: form.icon ? form.icon : null,
      };
      if (dialogMode.value === "create") {
        await createPerson(payload as PersonCreate);
        ElMessage.success("人员创建成功");
      } else {
        await updatePerson(editingId.value as number, payload as PersonUpdate);
        ElMessage.success("人员更新成功");
      }
      dialogVisible.value = false;
      loadData();
    } catch {
      // 拦截器统一提示
    } finally {
      submitting.value = false;
    }
  });
}

function selectIcon(key: string) {
  form.icon = key;
  formRef.value?.clearValidate(["icon"]);
}

// 查看态：根据 icon key 解析原型约定的安全帽颜色
function iconColor(key: string): string {
  return PERSON_ICONS.find((i) => i.key === key)?.color ?? "#909399";
}

// ---- 查看弹窗（只读）----
const viewVisible = ref(false);
const viewData = ref<Person | null>(null);
function openView(row: Person) {
  viewData.value = row;
  viewVisible.value = true;
}

async function handleDelete(row: Person) {
  try {
    await ElMessageBox.confirm("您确认删除当前人员？", "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deletePerson(row.id);
    ElMessage.success("人员已删除");
    loadData();
  } catch {
    // 拦截器统一提示
  }
}

// ---- 批量选择 / 批量删除（统一交互，见 useBatchSelection + BatchActions）----
const {
  tableRef,
  selectedRows,
  batchDeleting,
  onSelectionChange,
  clearSelection,
  onBatchDelete,
} = useBatchSelection({
  deleteApi: batchDeletePersons,
  reload: () => loadData(),
  label: "人员",
});

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      // 拦截器已处理
    }
  }
  // 默认项目：优先路由 ?project_id=（写回 store），否则取大屏选中项目
  const qid = Number(route.query.project_id);
  if (Number.isFinite(qid) && qid > 0) {
    filters.project_id = qid;
    projectStore.setSelectedProject(qid);
  } else if (projectStore.selectedProjectId != null) {
    filters.project_id = projectStore.selectedProjectId;
  }
  loadProjects();
  loadData();
});
</script>

<template>
  <div class="person-page">
    <div class="toolbar">
      <el-select
        v-model="filters.project_id"
        placeholder="项目名称"
        clearable
        class="filter-item"
      >
        <el-option
          v-for="[id, name] in projectMap"
          :key="id"
          :label="name"
          :value="id"
        />
      </el-select>
      <el-input
        v-model="filters.name"
        placeholder="姓名"
        clearable
        class="filter-item"
        @keyup.enter="handleSearch"
      />
      <el-select
        v-model="filters.person_type"
        placeholder="人员类型"
        clearable
        class="filter-item"
      >
        <el-option v-for="t in PERSON_TYPES" :key="t" :label="t" :value="t" />
      </el-select>
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate"
        >新增</el-button
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
      ref="tableRef"
      v-loading="loading"
      :data="tableData"
      row-key="id"
      border
      stripe
      class="table"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="48" />
      <el-table-column label="序号" width="64" align="center">
        <template #default="{ $index }">{{ (page - 1) * size + $index + 1 }}</template>
      </el-table-column>
      <el-table-column label="项目名称" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column prop="name" label="姓名" width="120" />
      <el-table-column prop="person_no" label="人员编号" width="130" />
      <el-table-column label="人员类型" width="120">
        <template #default="{ row }">{{ row.person_type || "—" }}</template>
      </el-table-column>
      <el-table-column label="人员性别" width="90">
        <template #default="{ row }">{{ row.gender || "—" }}</template>
      </el-table-column>
      <el-table-column prop="phone" label="电话号码" width="150" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button link type="info" @click="openView(row)">查看</el-button>
          <el-button v-if="canDelete" link type="danger" @click="handleDelete(row)"
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
        @change="loadData"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增人员' : '编辑人员'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="项目名称" prop="project_id">
          <el-select v-model="form.project_id" placeholder="请选择项目名称" class="full">
            <el-option
              v-for="[id, name] in projectMap"
              :key="id"
              :label="name"
              :value="id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="人员编号" prop="person_no">
          <el-input v-model="form.person_no" placeholder="请输入人员编号" />
        </el-form-item>
        <el-form-item label="人员姓名" prop="name">
          <el-input v-model="form.name" placeholder="请输入人员姓名" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select
            v-model="form.gender"
            placeholder="请选择性别"
            class="full"
            clearable
          >
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="电话号码" prop="phone">
          <el-input v-model="form.phone" placeholder="请输入电话号码" />
        </el-form-item>
        <el-form-item label="人员类型" prop="person_type">
          <el-select
            v-model="form.person_type"
            placeholder="请选择人员类型"
            class="full"
            clearable
          >
            <el-option v-for="t in PERSON_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="人员图标" prop="icon">
          <div class="icon-picker">
            <button
              v-for="opt in PERSON_ICONS"
              :key="opt.key"
              type="button"
              class="icon-option"
              :class="{ active: form.icon === opt.key }"
              :style="{ '--c': opt.color }"
              @click="selectIcon(opt.key)"
            >
              <el-icon><UserFilled /></el-icon>
            </button>
          </div>
        </el-form-item>
      </el-form>
      <el-divider v-if="dialogMode === 'edit'" content-position="left"
        >人员档案图 / 附件</el-divider
      >
      <AttachmentManager
        v-if="dialogMode === 'edit'"
        entity-type="person"
        :entity-id="editingId"
      />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit"
          >确定</el-button
        >
      </template>
    </el-dialog>

    <el-dialog
      v-model="viewVisible"
      title="查看人员"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form label-width="92px" :disabled="true">
        <el-form-item label="项目名称">
          <el-select
            :model-value="viewData ? viewData.project_id : undefined"
            class="full"
            disabled
          >
            <el-option
              v-for="[id, name] in projectMap"
              :key="id"
              :label="name"
              :value="id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="人员编号" required>
          <el-input :model-value="viewData?.person_no" disabled />
        </el-form-item>
        <el-form-item label="电话号码" required>
          <el-input :model-value="viewData?.phone || ''" disabled />
        </el-form-item>
        <el-form-item label="人员类型" required>
          <el-select :model-value="viewData?.person_type" class="full" disabled>
            <el-option v-for="t in PERSON_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="人员姓名" required>
          <el-input :model-value="viewData?.name" disabled />
        </el-form-item>
        <el-form-item label="性别">
          <el-select :model-value="viewData?.gender" class="full" disabled>
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="人员图标" required>
          <div class="icon-picker icon-picker--view">
            <span
              v-if="viewData?.icon"
              class="icon-option static"
              :style="{ '--c': iconColor(viewData.icon) }"
            >
              <el-icon><UserFilled /></el-icon>
            </span>
            <span v-else class="icon-empty">未设置</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="viewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.person-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.filter-item {
  width: 200px;
}
.full {
  width: 100%;
}
.icon-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.icon-option {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 2px solid #fff;
  background: var(--c);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  box-shadow: 0 0 0 1px #dcdfe6;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.icon-option:hover {
  transform: scale(1.06);
}
.icon-option.active {
  box-shadow: 0 0 0 2px var(--c);
  transform: scale(1.12);
}
.icon-picker--view {
  gap: 8px;
}
/* 查看态：图标只读展示，去掉可交互态 */
.icon-picker--view .icon-option {
  cursor: default;
}
.icon-picker--view .icon-option:hover {
  transform: none;
}
.icon-picker--view .icon-option.static {
  transform: none;
}
.icon-empty {
  color: #909399;
  font-size: 13px;
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
