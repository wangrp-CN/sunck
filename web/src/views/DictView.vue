<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import {
  createDictItem,
  createDictType,
  deleteDictItem,
  deleteDictType,
  fetchDictTypes,
  updateDictItem,
  updateDictType,
  type DictItem,
  type DictType,
} from "@/api/dict";

const auth = useAuthStore();
const canCreate = computed(
  () => auth.user?.permission_codes.includes("dict:create") ?? false,
);
const canUpdate = computed(
  () => auth.user?.permission_codes.includes("dict:update") ?? false,
);
const canDelete = computed(
  () => auth.user?.permission_codes.includes("dict:delete") ?? false,
);

const loading = ref(false);
const keyword = ref("");
const tableData = ref<DictType[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);

// 当前选中类型（右侧字典项面板）
const currentType = ref<DictType | null>(null);

async function load() {
  loading.value = true;
  try {
    const data = await fetchDictTypes({
      keyword: keyword.value || undefined,
      page: page.value,
      size: size.value,
    });
    tableData.value = data.items;
    total.value = data.total;
    // 刷新当前选中类型
    if (currentType.value) {
      currentType.value =
        data.items.find((t) => t.code === currentType.value?.code) ?? null;
    }
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.value = 1;
  load();
}

function selectType(row: DictType) {
  currentType.value = row;
}

// ----- 类型新增/编辑 -----
const typeDialogVisible = ref(false);
const typeEditing = ref<DictType | null>(null);
const typeFormRef = ref<FormInstance>();
const typeForm = reactive({ code: "", name: "", description: "" });
const typeRules: FormRules = {
  code: [{ required: true, message: "请输入类型编码", trigger: "blur" }],
  name: [{ required: true, message: "请输入类型名称", trigger: "blur" }],
};

function openTypeDialog(row?: DictType) {
  typeEditing.value = row ?? null;
  typeForm.code = row?.code ?? "";
  typeForm.name = row?.name ?? "";
  typeForm.description = row?.description ?? "";
  typeDialogVisible.value = true;
}

async function submitType() {
  if (!typeFormRef.value) return;
  await typeFormRef.value.validate(async (valid) => {
    if (!valid) return;
    if (typeEditing.value) {
      await updateDictType(typeEditing.value.code, {
        name: typeForm.name,
        description: typeForm.description || null,
      });
      ElMessage.success("更新成功");
    } else {
      await createDictType({
        code: typeForm.code.trim(),
        name: typeForm.name,
        description: typeForm.description || null,
        items: [],
      });
      ElMessage.success("创建成功");
    }
    typeDialogVisible.value = false;
    load();
  });
}

async function removeType(row: DictType) {
  await ElMessageBox.confirm(
    `确认删除字典类型「${row.name}」？其下字典项将一并删除。`,
    "删除确认",
    { type: "warning" },
  );
  await deleteDictType(row.code);
  ElMessage.success("删除成功");
  if (currentType.value?.code === row.code) currentType.value = null;
  load();
}

// ----- 字典项新增/编辑 -----
const itemDialogVisible = ref(false);
const itemEditing = ref<DictItem | null>(null);
const itemFormRef = ref<FormInstance>();
const itemForm = reactive({
  label: "",
  value: "",
  sort: 0,
  enabled: true,
  remark: "",
  ext: "",
});
const itemRules: FormRules = {
  label: [{ required: true, message: "请输入显示名称", trigger: "blur" }],
  value: [{ required: true, message: "请输入存储值", trigger: "blur" }],
};

function openItemDialog(row?: DictItem) {
  itemEditing.value = row ?? null;
  itemForm.label = row?.label ?? "";
  itemForm.value = row?.value ?? "";
  itemForm.sort = row?.sort ?? (currentType.value?.items.length ?? 0) + 1;
  itemForm.enabled = row?.enabled ?? true;
  itemForm.remark = row?.remark ?? "";
  itemForm.ext = row?.ext ?? "";
  itemDialogVisible.value = true;
}

async function submitItem() {
  if (!itemFormRef.value || !currentType.value) return;
  const typeCode = currentType.value.code;
  await itemFormRef.value.validate(async (valid) => {
    if (!valid) return;
    const payload = {
      label: itemForm.label,
      value: itemForm.value.trim(),
      sort: itemForm.sort,
      enabled: itemForm.enabled,
      remark: itemForm.remark || null,
      ext: itemForm.ext || null,
    };
    if (itemEditing.value) {
      await updateDictItem(itemEditing.value.id, payload);
      ElMessage.success("更新成功");
    } else {
      await createDictItem(typeCode, payload);
      ElMessage.success("新增成功");
    }
    itemDialogVisible.value = false;
    load();
  });
}

async function toggleItem(row: DictItem) {
  await updateDictItem(row.id, { enabled: !row.enabled });
  ElMessage.success(row.enabled ? "已停用" : "已启用");
  load();
}

async function removeItem(row: DictItem) {
  await ElMessageBox.confirm(`确认删除字典项「${row.label}」？`, "删除确认", {
    type: "warning",
  });
  await deleteDictItem(row.id);
  ElMessage.success("删除成功");
  load();
}

onMounted(load);
</script>

<template>
  <div class="dict-page">
    <el-row :gutter="12">
      <!-- 左：字典类型 -->
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>字典类型</span>
              <div class="toolbar">
                <el-input
                  v-model="keyword"
                  placeholder="编码/名称搜索"
                  clearable
                  style="width: 180px"
                  @keyup.enter="handleSearch"
                  @clear="handleSearch"
                />
                <el-button type="primary" @click="handleSearch">查询</el-button>
                <el-button v-if="canCreate" type="success" @click="openTypeDialog()">
                  新增类型
                </el-button>
              </div>
            </div>
          </template>

          <el-table
            v-loading="loading"
            :data="tableData"
            highlight-current-row
            @current-change="(row: DictType | null) => row && selectType(row)"
          >
            <el-table-column prop="code" label="编码" min-width="140" />
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column label="内置" width="70" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.system" type="warning" size="small">内置</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="项数" width="70" align="center">
              <template #default="{ row }">{{ row.items.length }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="canUpdate"
                  link
                  type="primary"
                  size="small"
                  @click.stop="openTypeDialog(row)"
                >
                  编辑
                </el-button>
                <el-button
                  v-if="canDelete && !row.system"
                  link
                  type="danger"
                  size="small"
                  @click.stop="removeType(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-model:current-page="page"
            v-model:page-size="size"
            :total="total"
            layout="total, prev, pager, next"
            class="pager"
            @current-change="load"
          />
        </el-card>
      </el-col>

      <!-- 右：字典项 -->
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>
                字典项
                <el-tag v-if="currentType" size="small" class="type-tag">
                  {{ currentType.name }}（{{ currentType.code }}）
                </el-tag>
              </span>
              <el-button
                v-if="canUpdate && currentType"
                type="success"
                size="small"
                @click="openItemDialog()"
              >
                新增字典项
              </el-button>
            </div>
          </template>

          <el-empty v-if="!currentType" description="点击左侧类型查看字典项" />
          <el-table v-else :data="currentType.items">
            <el-table-column prop="sort" label="排序" width="70" align="center" />
            <el-table-column prop="label" label="显示名称" min-width="120" />
            <el-table-column prop="value" label="存储值" min-width="110" />
            <el-table-column label="状态" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                  {{ row.enabled ? "启用" : "停用" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="备注" min-width="100" show-overflow-tooltip />
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="canUpdate"
                  link
                  type="primary"
                  size="small"
                  @click="openItemDialog(row)"
                >
                  编辑
                </el-button>
                <el-button v-if="canUpdate" link size="small" @click="toggleItem(row)">
                  {{ row.enabled ? "停用" : "启用" }}
                </el-button>
                <el-button
                  v-if="canUpdate && !currentType.system"
                  link
                  type="danger"
                  size="small"
                  @click="removeItem(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 类型对话框 -->
    <el-dialog
      v-model="typeDialogVisible"
      :title="typeEditing ? '编辑字典类型' : '新增字典类型'"
      width="460px"
    >
      <el-form ref="typeFormRef" :model="typeForm" :rules="typeRules" label-width="80px">
        <el-form-item label="编码" prop="code">
          <el-input
            v-model="typeForm.code"
            :disabled="!!typeEditing"
            placeholder="如 device_status"
          />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="typeForm.name" placeholder="如 设备状态" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="typeForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="typeDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitType">确定</el-button>
      </template>
    </el-dialog>

    <!-- 字典项对话框 -->
    <el-dialog
      v-model="itemDialogVisible"
      :title="itemEditing ? '编辑字典项' : '新增字典项'"
      width="460px"
    >
      <el-form ref="itemFormRef" :model="itemForm" :rules="itemRules" label-width="80px">
        <el-form-item label="显示名称" prop="label">
          <el-input v-model="itemForm.label" />
        </el-form-item>
        <el-form-item label="存储值" prop="value">
          <el-input v-model="itemForm.value" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="itemForm.sort" :min="0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="itemForm.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="itemForm.remark" />
        </el-form-item>
        <el-form-item label="扩展">
          <el-input v-model="itemForm.ext" placeholder="颜色/图标等，可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitItem">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dict-page {
  padding: 4px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.toolbar {
  display: flex;
  gap: 8px;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.type-tag {
  margin-left: 8px;
}
</style>
