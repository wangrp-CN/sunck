<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  fetchMenus,
  fetchMenuOptions,
  createMenu,
  updateMenu,
  deleteMenu,
  batchDeleteMenus,
  type MenuItem,
  type MenuTreeItem,
  type MenuCreate,
} from "@/api/menu";
import BatchActions from "@/components/BatchActions.vue";
import { useBatchSelection } from "@/composables/useBatchSelection";
import { useAuthStore } from "@/stores/auth";
import {
  CirclePlus,
  Delete,
  Edit,
  MoreFilled,
  Refresh,
  Search,
  Setting,
  View,
} from "@element-plus/icons-vue";

const auth = useAuthStore();
const canDelete = computed(() => auth.hasPermission("menu:delete"));
const canAdd = computed(() => auth.hasPermission("menu:add"));
const canEdit = computed(() => auth.hasPermission("menu:edit"));

const loading = ref(false);
const tableData = ref<MenuTreeItem[]>([]);
const tableRef = ref<any>(null);

const keyword = ref("");
const typeFilter = ref<number | null>(null);
const statusFilter = ref<boolean | null>(null);

const parentOptions = ref<MenuItem[]>([]);

function typeLabel(type: number): string {
  switch (type) {
    case 1:
      return "目录";
    case 2:
      return "菜单";
    case 3:
      return "按钮";
    default:
      return String(type);
  }
}

function typeTag(type: number): string {
  switch (type) {
    case 1:
      return "info";
    case 2:
      return "success";
    case 3:
      return "warning";
    default:
      return "";
  }
}

async function loadTable() {
  loading.value = true;
  try {
    const tree = await fetchMenus({
      keyword: keyword.value || undefined,
      type: typeFilter.value ?? undefined,
      status: statusFilter.value ?? undefined,
    });
    tableData.value = tree;
  } catch {
    // 拦截器统一提示
  } finally {
    loading.value = false;
  }
}

async function loadOptions() {
  parentOptions.value = await fetchMenuOptions();
}

function handleSearch() {
  loadTable();
}

function handleReset() {
  keyword.value = "";
  typeFilter.value = null;
  statusFilter.value = null;
  loadTable();
}

function handleRefresh() {
  loadTable();
}

function handleExpandAll() {
  tableRef.value?.expandAll?.();
}

function handleCollapseAll() {
  tableRef.value?.collapseAll?.();
}

// ── 批量选择 / 批量删除 ──
const {
  selectedRows,
  batchDeleting,
  onSelectionChange,
  clearSelection,
  onBatchDelete,
} = useBatchSelection({
  deleteApi: batchDeleteMenus,
  reload: () => loadTable(),
  label: "菜单",
});

// ── 对话框 ──
const dialogVisible = ref(false);
const dialogMode = ref<"create" | "edit" | "detail" | "add-child">("create");
const submitting = ref(false);

const formRef = ref<any>(null);
const form = reactive({
  id: undefined as number | undefined,
  name: "",
  code: "",
  menuType: 1 as 1 | 2 | 3,
  isRoute: true,
  parent_id: null as number | null,
  path: "",
  component: "",
  icon: "",
  sort: 0,
  status: true,
  redirect: "",
  is_hidden: false,
  is_cache: false,
  is_affix: false,
  is_external: false,
  remark: "",
});

const dialogTitle = computed(() => {
  switch (dialogMode.value) {
    case "create":
      return "新增";
    case "edit":
      return "编辑";
    case "detail":
      return "详情";
    case "add-child":
      return "添加子菜单";
    default:
      return "";
  }
});

const isReadonly = computed(() => dialogMode.value === "detail");

function resetForm() {
  form.id = undefined;
  form.name = "";
  form.code = "";
  form.menuType = 1;
  form.isRoute = true;
  form.parent_id = null;
  form.path = "";
  form.component = "";
  form.icon = "";
  form.sort = 0;
  form.status = true;
  form.redirect = "";
  form.is_hidden = false;
  form.is_cache = false;
  form.is_affix = false;
  form.is_external = false;
  form.remark = "";
}

function deriveMenuType(row: MenuItem): 1 | 2 | 3 {
  if (row.type === 3) return 3;
  return row.parent_id == null ? 1 : 2;
}

function fillForm(row: MenuItem) {
  form.id = row.id;
  form.name = row.name;
  form.code = row.code;
  form.menuType = deriveMenuType(row);
  form.isRoute = row.type === 2;
  form.parent_id = row.parent_id;
  form.path = row.path || "";
  form.component = row.component || "";
  form.icon = row.icon || "";
  form.sort = row.sort;
  form.status = row.status;
  form.redirect = row.redirect || "";
  form.is_hidden = row.is_hidden;
  form.is_cache = row.is_cache;
  form.is_affix = row.is_affix;
  form.is_external = row.is_external;
  form.remark = row.remark || "";
}

function openCreate() {
  dialogMode.value = "create";
  resetForm();
  form.menuType = 1;
  form.isRoute = true;
  form.parent_id = null;
  dialogVisible.value = true;
}

function openEdit(row: MenuItem) {
  dialogMode.value = "edit";
  resetForm();
  fillForm(row);
  dialogVisible.value = true;
}

function openDetail(row: MenuItem) {
  dialogMode.value = "detail";
  resetForm();
  fillForm(row);
  dialogVisible.value = true;
}

function openAddChild(row: MenuItem) {
  dialogMode.value = "add-child";
  resetForm();
  form.menuType = 2;
  form.isRoute = true;
  form.parent_id = row.id;
  dialogVisible.value = true;
}

function computedType(): number {
  if (form.menuType === 3) return 3;
  return form.isRoute ? 2 : 1;
}

function buildPayload(): MenuCreate {
  return {
    name: form.name,
    code: form.code,
    type: computedType(),
    parent_id: form.parent_id,
    path: form.path || null,
    component: form.component || null,
    icon: form.icon || null,
    sort: form.sort,
    status: form.status,
    redirect: form.redirect || null,
    is_hidden: form.is_hidden,
    is_cache: form.is_cache,
    is_affix: form.is_affix,
    is_external: form.is_external,
    remark: form.remark || null,
  };
}

async function submit() {
  if (isReadonly.value) {
    dialogVisible.value = false;
    return;
  }

  // 子菜单/按钮必须选择上级
  if ((form.menuType === 2 || form.menuType === 3) && form.parent_id == null) {
    ElMessage.warning("请选择上级菜单");
    return;
  }

  submitting.value = true;
  try {
    const data = buildPayload();
    if (dialogMode.value === "create" || dialogMode.value === "add-child") {
      await createMenu(data);
      ElMessage.success("菜单创建成功");
    } else {
      await updateMenu(form.id!, data);
      ElMessage.success("菜单更新成功");
    }
    dialogVisible.value = false;
    loadTable();
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false;
  }
}

async function remove(row: MenuItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除菜单「${row.name}」？将同时删除其所有子菜单。`,
      "提示",
      { type: "warning" },
    );
  } catch {
    return;
  }
  try {
    await deleteMenu(row.id);
    ElMessage.success("已删除");
    loadTable();
  } catch {
    // 拦截器提示
  }
}

onMounted(async () => {
  await loadOptions();
  loadTable();
});
</script>

<template>
  <div class="page">
    <div class="tool-bar">
      <div class="left-actions">
        <el-button v-if="canAdd" type="primary" :icon="CirclePlus" @click="openCreate">
          新增
        </el-button>
        <el-button v-if="canDelete" type="danger" plain :icon="Delete" @click="onBatchDelete">
          批量删除
        </el-button>
      </div>
      <div class="right-filters">
        <el-input
          v-model="keyword"
          placeholder="按名称/标识/路径搜索"
          clearable
          class="search-input"
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleReset"
        />
        <el-select
          v-model="typeFilter"
          placeholder="类型"
          clearable
          class="filter-select"
          @change="handleSearch"
        >
          <el-option label="目录" :value="1" />
          <el-option label="菜单" :value="2" />
          <el-option label="按钮" :value="3" />
        </el-select>
        <el-select
          v-model="statusFilter"
          placeholder="状态"
          clearable
          class="filter-select"
          @change="handleSearch"
        >
          <el-option label="启用" :value="true" />
          <el-option label="停用" :value="false" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button :icon="Refresh" circle title="刷新" @click="handleRefresh" />
      </div>
    </div>

    <BatchActions
      v-if="canDelete"
      :selected="selectedRows.length"
      :loading="batchDeleting"
      @batch-delete="onBatchDelete"
      @clear="clearSelection"
    />

    <div class="tree-actions">
      <el-button link type="primary" @click="handleExpandAll">展开全部</el-button>
      <el-button link type="primary" @click="handleCollapseAll">折叠全部</el-button>
    </div>

    <el-table
      ref="tableRef"
      v-loading="loading"
      :data="tableData"
      border
      stripe
      row-key="id"
      default-expand-all
      :tree-props="{ children: 'children', hasChildren: 'hasChildren' }"
      @selection-change="onSelectionChange"
    >
      <el-table-column
        v-if="canDelete"
        type="selection"
        width="48"
        :reserve-selection="false"
        fixed="left"
      />
      <el-table-column label="菜单名称" min-width="200" prop="name">
        <template #default="{ row }">
          <span class="menu-name" :class="{ 'menu-name--parent': row.type === 1 }">
            <span>{{ row.name }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="菜单类型" width="90">
        <template #default="{ row }">
          <el-tag :type="typeTag(row.type)" size="small">{{ typeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="icon" label="icon" width="100" />
      <el-table-column prop="component" label="组件" min-width="180" show-overflow-tooltip />
      <el-table-column prop="path" label="路径" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status ? 'success' : 'info'" size="small">
            {{ row.status ? "启用" : "停用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canEdit"
            link
            type="primary"
            :icon="Edit"
            @click="openEdit(row)"
          >
            编辑
          </el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => {
            if (cmd === 'detail') openDetail(row);
            else if (cmd === 'addChild') openAddChild(row);
            else if (cmd === 'delete') remove(row);
          }">
            <el-button link type="primary">
              更多<el-icon class="el-icon--right"><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="detail" :icon="View">详情</el-dropdown-item>
                <el-dropdown-item v-if="canAdd" command="addChild" :icon="CirclePlus">
                  添加下级
                </el-dropdown-item>
                <el-dropdown-item v-if="canDelete" command="delete" :icon="Delete">
                  删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="620px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="form"
        label-width="110px"
        :disabled="isReadonly"
      >
        <el-form-item label="菜单类型" required>
          <el-radio-group v-model="form.menuType">
            <el-radio :value="1">一级菜单</el-radio>
            <el-radio :value="2">子菜单</el-radio>
            <el-radio :value="3">按钮/权限</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="菜单名称" required>
          <el-input v-model="form.name" placeholder="请输入菜单名称" />
        </el-form-item>

        <el-form-item
          v-if="form.menuType === 2 || form.menuType === 3"
          label="上级菜单"
          required
        >
          <el-select
            v-model="form.parent_id"
            placeholder="请选择上级菜单"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="o in parentOptions"
              :key="o.id"
              :label="`${o.name} (${o.code})`"
              :value="o.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="菜单路径" :required="form.menuType !== 3">
          <el-input v-model="form.path" placeholder="请输入菜单路径" />
        </el-form-item>

        <el-form-item label="前端组件" :required="form.menuType === 2">
          <el-input v-model="form.component" placeholder="请输入前端组件" />
        </el-form-item>

        <el-form-item label="默认跳转地址">
          <el-input v-model="form.redirect" placeholder="请输入路由参数 redirect" />
        </el-form-item>

        <el-form-item label="菜单图标">
          <el-input v-model="form.icon" placeholder="点击选择图标">
            <template #append>
              <el-icon size="16"><Setting /></el-icon>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" style="width: 100%" />
        </el-form-item>

        <el-form-item label="是否路由菜单">
          <el-switch
            v-model="form.isRoute"
            :disabled="form.menuType === 3"
            inline-prompt
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>

        <el-form-item label="隐藏路由">
          <el-switch
            v-model="form.is_hidden"
            inline-prompt
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>

        <el-form-item label="是否缓存路由">
          <el-switch
            v-model="form.is_cache"
            inline-prompt
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>

        <el-form-item label="聚合路由">
          <el-switch
            v-model="form.is_affix"
            inline-prompt
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>

        <el-form-item label="打开方式">
          <el-switch
            v-model="form.is_external"
            inline-prompt
            active-text="外部"
            inactive-text="内部"
          />
        </el-form-item>

        <el-form-item label="状态">
          <el-switch
            v-model="form.status"
            inline-prompt
            active-text="启用"
            inactive-text="停用"
          />
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">
          {{ isReadonly ? "关闭" : "取消" }}
        </el-button>
        <el-button v-if="!isReadonly" type="primary" :loading="submitting" @click="submit">
          确定
        </el-button>
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
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.left-actions,
.right-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.search-input {
  width: 220px;
}
.filter-select {
  width: 110px;
}
.tree-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
}
.menu-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  /* 父级与子级统一字体/字号/字重/字间距与对齐，层级仅靠树缩进 + 类型标签区分 */
  font-size: 14px;
  font-weight: 400;
  letter-spacing: 0.2px;
  color: #303133;
}
/* 父级(目录)略加粗以强化分组归属，但文本排版与子级保持一致 */
.menu-name--parent {
  font-weight: 600;
}
.menu-icon {
  color: #606266;
}
.icon-placeholder {
  color: #909399;
}
</style>
