<script setup lang="ts">
import { ref, watch } from "vue";
import { fetchJobsByFence } from "@/api/job";
import type { WorkPlan, WorkPlanRule } from "@/types";

const props = defineProps<{
  modelValue: boolean;
  fenceId: number | null;
  fenceName: string;
}>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();

const plans = ref<WorkPlan[]>([]);
const loading = ref(false);

const TRIGGER_LABELS: Record<string, string> = {
  fence_intrusion: "围栏侵入",
  distance_too_close: "间距过近",
  device_alarm: "设备告警",
};
const TARGET_LABELS: Record<string, string> = {
  person: "人机",
  machine: "大型机械",
  train: "列车",
  all: "全部",
};

function statusType(s: string): "" | "info" | "warning" | "success" {
  if (s === "执行中") return "warning";
  if (s === "已完成") return "success";
  if (s === "草稿") return "info";
  return "";
}
function fmtTime(t: string | null | undefined): string {
  if (!t) return "—";
  return t.replace("T", " ").slice(0, 16);
}
function ruleSummary(rule?: WorkPlanRule | null): string {
  if (!rule) return "无规则配置";
  const parts: string[] = [];
  if (rule.monitor_target)
    parts.push(`监控对象：${TARGET_LABELS[rule.monitor_target] || rule.monitor_target}`);
  if (rule.trigger_conditions && rule.trigger_conditions.length)
    parts.push(`触发条件：${rule.trigger_conditions.map((t) => TRIGGER_LABELS[t] || t).join("、")}`);
  if (rule.dwell_time != null) parts.push(`持续 ${rule.dwell_time} 秒后告警`);
  return parts.length ? parts.join("；") : "无规则配置";
}

watch(
  () => [props.modelValue, props.fenceId] as const,
  ([vis, fid]) => {
    if (!vis || fid == null) return;
    loading.value = true;
    plans.value = [];
    fetchJobsByFence(fid as number)
      .then((data) => (plans.value = data))
      .catch(() => {
        /* 拦截器已提示 */
      })
      .finally(() => (loading.value = false));
  },
  { immediate: true },
);

function close() {
  emit("update:modelValue", false);
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`围栏「${fenceName}」关联作业计划`"
    width="640px"
    @update:model-value="close"
  >
    <div v-loading="loading" class="plan-pop">
      <el-empty
        v-if="!loading && plans.length === 0"
        description="该围栏未关联任何作业计划"
        :image-size="70"
      />
      <div v-for="p in plans" :key="p.id" class="plan-card">
        <div class="plan-head">
          <span class="plan-name">{{ p.name }}</span>
          <el-tag :type="statusType(p.status)" size="small" effect="dark">{{ p.status }}</el-tag>
          <el-tag v-if="p.active" type="success" size="small" effect="plain">激活中</el-tag>
          <span class="plan-id">#{{ p.id }}</span>
        </div>
        <div class="plan-row">
          <span class="k">所属项目</span>
          <span class="v">{{ p.project_name || "—" }}</span>
        </div>
        <div class="plan-row">
          <span class="k">作业时间窗</span>
          <span class="v">{{ fmtTime(p.plan_start) }} ~ {{ fmtTime(p.plan_end) }}</span>
        </div>
        <div class="plan-row">
          <span class="k">监控规则</span>
          <span class="v">{{ ruleSummary(p.rule) }}</span>
        </div>
        <div class="plan-row">
          <span class="k">绑定设备</span>
          <span class="v">
            <template v-if="p.devices && p.devices.length">
              <el-tag v-for="d in p.devices" :key="d.device_no" size="small" class="chip">
                {{ d.device_no }}
              </el-tag>
            </template>
            <span v-else>—</span>
          </span>
        </div>
        <div class="plan-row">
          <span class="k">绑定机械</span>
          <span class="v">
            <template v-if="p.machines && p.machines.length">
              <el-tag v-for="m in p.machines" :key="m.id" size="small" class="chip" type="warning">
                {{ m.name }}
              </el-tag>
            </template>
            <span v-else>—</span>
          </span>
        </div>
        <div class="plan-row">
          <span class="k">作业人员</span>
          <span class="v">
            <template v-if="p.persons && p.persons.length">
              <el-tag v-for="p2 in p.persons" :key="p2.id" size="small" class="chip" type="info">
                {{ p2.name }}
              </el-tag>
            </template>
            <span v-else>—</span>
          </span>
        </div>
        <div class="plan-row">
          <span class="k">绑定围栏</span>
          <span class="v">
            <template v-if="p.fences && p.fences.length">
              <el-tag v-for="f in p.fences" :key="f.id" size="small" class="chip" type="success">
                {{ f.name || "#" + f.id }}
              </el-tag>
            </template>
            <span v-else>—</span>
          </span>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.plan-pop {
  max-height: 60vh;
  overflow-y: auto;
}
.plan-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fafbfc;
}
.plan-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.plan-name {
  font-weight: 700;
  font-size: 15px;
  color: #303133;
}
.plan-id {
  margin-left: auto;
  color: #c0c4cc;
  font-size: 12px;
}
.plan-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
  margin-bottom: 6px;
}
.plan-row .k {
  width: 72px;
  color: #909399;
  flex-shrink: 0;
}
.plan-row .v {
  color: #303133;
  flex: 1;
}
.chip {
  margin: 0 4px 4px 0;
}
</style>
