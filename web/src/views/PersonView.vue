<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createPerson,
  deletePerson,
  fetchPersons,
  updatePerson,
} from "@/api/person";
import { fetchProjects } from "@/api/project";
import type { Person, PersonCreate, PersonUpdate, Project } from "@/types";
import AttachmentManager from "@/components/AttachmentManager.vue";

const auth = useAuthStore();

const canAdd = computed(() => auth.user?.permission_codes.includes("person:add") ?? false);
const canEdit = computed(() => auth.user?.permission_codes.includes("person:edit") ?? false);
const canDelete = computed(() => auth.user?.permission_codes.includes("person:delete") ?? false);

const loading = ref(false);
const keyword = ref("");
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
      keyword: keyword.value || undefined,
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
  project_id: undefined as number | undefined,
  person_no: "",
  name: "",
  gender: "" as string,
  phone: "",
  person_type: "",
  device_no: "",
});

const form = reactive(emptyForm());

const rules: FormRules = {
  project_id: [{ required: true, message: "请选择归属项目", trigger: "change" }],
  person_no: [{ required: true, message: "请输入工号", trigger: "blur" }],
  name: [{ required: true, message: "请输入姓名", trigger: "blur" }],
};

function openCreate() {
  dialogMode.value = "create";
  editingId.value = null;
  Object.assign(form, emptyForm());
  dialogVisible.value = true;
}

async function openEdit(row: Person) {
  dialogMode.value = "edit";
  editingId.value = row.id;
  Object.assign(form, {
    project_id: row.project_id ?? undefined,
    person_no: row.person_no,
    name: row.name,
    gender: row.gender ?? "",
    phone: row.phone ?? "",
    person_type: row.person_type ?? "",
    device_no: row.device_no ?? "",
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
        device_no: form.device_no ? form.device_no : null,
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

async function handleDelete(row: Person) {
  try {
    await ElMessageBox.confirm(
      `确定删除人员「${row.name}」吗？该操作将软删人员。`,
      "删除确认",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
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

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.loadProfile();
    } catch {
      // 拦截器已处理
    }
  }
  loadProjects();
  loadData();
});
</script>

<template>
  <div class="person-page">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按姓名/工号搜索"
        clearable
        class="search-input"
        @keyup.enter="handleSearch"
        @clear="handleReset"
      />
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
      <el-button v-if="canAdd" type="success" @click="openCreate">新增人员</el-button>
    </div>

    <el-table v-loading="loading" :data="tableData" border stripe class="table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="person_no" label="工号" width="130" />
      <el-table-column prop="name" label="姓名" width="120" />
      <el-table-column label="性别" width="80">
        <template #default="{ row }">{{ row.gender || '—' }}</template>
      </el-table-column>
      <el-table-column prop="phone" label="电话" width="140" />
      <el-table-column label="人员类型" width="120">
        <template #default="{ row }">{{ row.person_type || '—' }}</template>
      </el-table-column>
      <el-table-column label="绑定设备" width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ row.device_no || '—' }}</template>
      </el-table-column>
      <el-table-column label="归属项目" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ projectName(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canDelete" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增人员' : '编辑人员'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="归属项目" prop="project_id">
          <el-select v-model="form.project_id" placeholder="请选择项目" class="full">
            <el-option
              v-for="[id, name] in projectMap"
              :key="id"
              :label="name"
              :value="id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="工号" prop="person_no">
          <el-input v-model="form.person_no" placeholder="人员工号" />
        </el-form-item>
        <el-form-item label="姓名" prop="name">
          <el-input v-model="form.name" placeholder="姓名" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.gender" placeholder="请选择" class="full" clearable>
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" placeholder="联系电话" />
        </el-form-item>
        <el-form-item label="人员类型">
          <el-input v-model="form.person_type" placeholder="如：防护/施工/管理" />
        </el-form-item>
        <el-form-item label="绑定设备">
          <el-input v-model="form.device_no" placeholder="定位设备编号（可选）" />
        </el-form-item>
      </el-form>
      <el-divider v-if="dialogMode === 'edit'" content-position="left">人员档案图 / 附件</el-divider>
      <AttachmentManager
        v-if="dialogMode === 'edit'"
        entity-type="person"
        :entity-id="editingId"
      />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.person-page { padding: 4px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.search-input { width: 240px; }
.full { width: 100%; }
.table { width: 100%; }
.pager { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
