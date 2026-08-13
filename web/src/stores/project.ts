import { defineStore } from "pinia";
import { ref } from "vue";

/**
 * 全局「当前选中项目」。
 *
 * 用途：大屏（项目详情大屏等）选中某个项目后写入本 store，
 * 其他列表页（如人员列表）可将「项目名称」筛选默认值联动为该选中项目，
 * 实现「默认 = 大屏选中的项目」。
 *
 * 同时持久化到 localStorage，避免跨页面/刷新后丢失；
 * 也兼容列表页通过路由 ?project_id= 跳入时直接预选（见各列表页 onMounted）。
 */
const STORAGE_KEY = "rail_monitor_selected_project_id";

function loadInitial(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

export const useProjectStore = defineStore("project", () => {
  const selectedProjectId = ref<number | null>(loadInitial());

  function setSelectedProject(id: number | null) {
    selectedProjectId.value = id && id > 0 ? id : null;
    try {
      if (selectedProjectId.value != null) {
        localStorage.setItem(STORAGE_KEY, String(selectedProjectId.value));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // 隐私模式 / SSR 等场景忽略
    }
  }

  return { selectedProjectId, setSelectedProject };
});
