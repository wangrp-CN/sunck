// 批量选择/批量删除 composable 单测：空选拦截、取消确认、跳过提示、清空与刷新
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ElMessage, ElMessageBox } from "element-plus";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: vi.fn() },
  };
});

import { useBatchSelection } from "@/composables/useBatchSelection";

const rows = [{ id: 1 }, { id: 2 }, { id: 3 }];

function setup(deleteApi = vi.fn().mockResolvedValue({ deleted: 3, total: 3, skipped: 0 })) {
  const reload = vi.fn();
  const batch = useBatchSelection({ deleteApi, reload, label: "人员" });
  return { batch, deleteApi, reload };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as never);
});

describe("useBatchSelection", () => {
  it("selection-change 同步已选行", () => {
    const { batch } = setup();
    batch.onSelectionChange(rows);
    expect(batch.selectedRows.value).toHaveLength(3);
  });

  it("未选中任何行时不弹确认也不调接口", async () => {
    const { batch, deleteApi } = setup();
    await batch.onBatchDelete();
    expect(vi.mocked(ElMessageBox.confirm)).not.toHaveBeenCalled();
    expect(deleteApi).not.toHaveBeenCalled();
  });

  it("确认后按 id 批量删除、清空选中并刷新列表", async () => {
    const { batch, deleteApi, reload } = setup();
    batch.onSelectionChange(rows);

    await batch.onBatchDelete();

    expect(deleteApi).toHaveBeenCalledWith([1, 2, 3]);
    expect(batch.selectedRows.value).toHaveLength(0);
    expect(reload).toHaveBeenCalled();
    expect(batch.batchDeleting.value).toBe(false);
    expect(vi.mocked(ElMessage.success)).toHaveBeenCalledWith("已删除 3 项");
  });

  it("确认文案带实体名与条数", async () => {
    const { batch } = setup();
    batch.onSelectionChange(rows.slice(0, 2));
    await batch.onBatchDelete();
    const [msg] = vi.mocked(ElMessageBox.confirm).mock.calls[0];
    expect(String(msg)).toContain("2 项人员");
  });

  it("部分被跳过时提示跳过条数", async () => {
    const api = vi.fn().mockResolvedValue({ deleted: 1, total: 3, skipped: 2 });
    const { batch } = setup(api);
    batch.onSelectionChange(rows);
    await batch.onBatchDelete();
    expect(vi.mocked(ElMessage.success)).toHaveBeenCalledWith(
      "已删除 1 项，2 项因无权访问或已删除被跳过",
    );
  });

  it("用户取消确认时不调接口", async () => {
    const { batch, deleteApi } = setup();
    batch.onSelectionChange(rows);
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    await batch.onBatchDelete();
    expect(deleteApi).not.toHaveBeenCalled();
  });

  it("接口异常时收敛错误并复位 loading", async () => {
    const api = vi.fn().mockRejectedValue(new Error("boom"));
    const { batch, reload } = setup(api);
    batch.onSelectionChange(rows);
    await batch.onBatchDelete();
    expect(batch.batchDeleting.value).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it("clearSelection 同时清除表格内部选中态", () => {
    const { batch } = setup();
    const clear = vi.fn();
    batch.tableRef.value = { clearSelection: clear };
    batch.onSelectionChange(rows);

    batch.clearSelection();

    expect(clear).toHaveBeenCalled();
    expect(batch.selectedRows.value).toHaveLength(0);
  });
});
