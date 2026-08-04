/**
 * 表格批量选择 + 批量删除的统一逻辑。
 *
 * 各列表页只需接入本 composable + <BatchActions>，即可获得一致的：
 * 1. 行多选（配合 el-table 的 `type="selection"` 列与 `row-key`，支持跨页保留选中）；
 * 2. 「已选择 N 项」实时计数；
 * 3. 批量删除：统一二次确认文案、统一结果提示、删除后清空选中并刷新分页列表。
 *
 * 用法：
 *   const batch = useBatchSelection<Person>({
 *     deleteApi: batchDeletePersons,
 *     reload: loadData,
 *     label: "人员",
 *   });
 */
import { ref, type Ref } from "vue";
import type { BatchDeleteResult } from "@/api/batch";

/** 批量选择所需的最小行结构 */
export interface RowWithId {
  id: number;
}

export interface UseBatchSelectionOptions<T extends RowWithId> {
  /** 批量删除接口（来自 @/api/*，内部走 POST {资源}/batch-delete） */
  deleteApi: (ids: number[]) => Promise<BatchDeleteResult>;
  /** 删除成功后刷新列表 */
  reload: () => void | Promise<void>;
  /** 实体中文名，用于确认弹窗文案，如「人员」「设备」 */
  label?: string;
  /** 自定义取 id（默认取 row.id） */
  idOf?: (row: T) => number;
}

export interface UseBatchSelectionReturn<T extends RowWithId> {
  /** 绑定到 el-table 的 ref，用于 clearSelection() */
  tableRef: Ref<{ clearSelection?: () => void } | null>;
  /** 当前选中行 */
  selectedRows: Ref<T[]>;
  /** 批量删除进行中 */
  batchDeleting: Ref<boolean>;
  /** el-table @selection-change */
  onSelectionChange: (rows: T[]) => void;
  /** 清空选中（同时清除表格内部选中态） */
  clearSelection: () => void;
  /** 批量删除（含二次确认） */
  onBatchDelete: () => Promise<void>;
}

export function useBatchSelection<T extends RowWithId = RowWithId>(
  options: UseBatchSelectionOptions<T>,
): UseBatchSelectionReturn<T> {
  const { deleteApi, reload, label = "数据", idOf } = options;

  const tableRef = ref<{ clearSelection?: () => void } | null>(null);
  const selectedRows = ref([]) as Ref<T[]>;
  const batchDeleting = ref(false);

  function onSelectionChange(rows: T[]) {
    selectedRows.value = rows ?? [];
  }

  function clearSelection() {
    selectedRows.value = [];
    tableRef.value?.clearSelection?.();
  }

  async function onBatchDelete() {
    const ids = selectedRows.value
      .map((row) => (idOf ? idOf(row) : row.id))
      .filter((id): id is number => typeof id === "number");
    if (ids.length === 0) return;

    try {
      await ElMessageBox.confirm(
        `确定删除已选择的 ${ids.length} 项${label}吗？该操作不可撤销。`,
        "批量删除确认",
        { type: "warning", confirmButtonText: "确定删除", cancelButtonText: "取消" },
      );
    } catch {
      return; // 用户取消
    }

    batchDeleting.value = true;
    try {
      const res = await deleteApi(ids);
      const deleted = res?.deleted ?? ids.length;
      const skipped = res?.skipped ?? 0;
      ElMessage.success(
        skipped > 0
          ? `已删除 ${deleted} 项，${skipped} 项因无权访问或已删除被跳过`
          : `已删除 ${deleted} 项`,
      );
      clearSelection();
      await reload();
    } catch {
      // 拦截器统一提示
    } finally {
      batchDeleting.value = false;
    }
  }

  return { tableRef, selectedRows, batchDeleting, onSelectionChange, clearSelection, onBatchDelete };
}
