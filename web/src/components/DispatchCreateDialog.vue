<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { listUsers } from "@/api/user";
import { createDispatch, type DispatchOptions, type DispatchPreset } from "@/api/dispatch";
import { getDispatchOptions } from "@/api/dispatch";

const props = defineProps<{
  modelValue: boolean;
  preset?: DispatchPreset | null;
}>();
const emit = defineEmits<{
  "update:modelValue": [boolean];
  created: [];
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

const form = ref({
  title: "",
  source_type: "manual",
  source_id: null as number | null,
  project_id: null as number | null,
  level: "" as string,
  root_cause_hint: "" as string,
  assignee_id: null as number | null,
  deadline: "" as string,
  description: "",
});
const options = ref<DispatchOptions>({ statuses: [], sources: [], levels: [] });
const users = ref<{ id: number; name: string }[]>([]);
const submitting = ref(false);

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      loadMeta();
      const p = props.preset;
      form.value = {
        title: p?.title || "",
        source_type: p?.source_type || "manual",
        source_id: p?.source_id ?? null,
        project_id: p?.project_id ?? null,
        level: p?.level || "",
        root_cause_hint: p?.root_cause_hint || "",
        assignee_id: null,
        deadline: "",
        description: "",
      };
    }
  },
);

async function loadMeta() {
  try {
    options.value = await getDispatchOptions();
  } catch {
    /* ignore */
  }
  try {
    const r = await listUsers({ page: 1, size: 200 });
    users.value = (r.items || []).map((u: any) => ({ id: u.id, name: u.nickname || u.username }));
  } catch {
    users.value = [];
  }
}

async function submit() {
  if (!form.value.title.trim()) {
    ElMessage.warning("请填写派单标题");
    return;
  }
  if (form.value.source_type === "manual" && !form.value.project_id) {
    ElMessage.warning("人工建单需选择归属项目");
    return;
  }
  submitting.value = true;
  try {
    await createDispatch({
      title: form.value.title.trim(),
      source_type: form.value.source_type,
      source_id: form.value.source_id,
      project_id: form.value.project_id,
      level: form.value.level || null,
      root_cause_hint: form.value.root_cause_hint || null,
      assignee_id: form.value.assignee_id,
      deadline: form.value.deadline || null,
      description: form.value.description || null,
    });
    ElMessage.success("派单已创建，已通知处理人");
    emit("created");
    visible.value = false;
  } catch (e: any) {
    ElMessage.error(e?.message || "创建失败");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="新建派单" width="520px" @closed="visible = false">
    <el-form label-width="92px">
      <el-form-item label="来源">
        <el-select v-model="form.source_type" style="width: 100%">
          <el-option v-for="s in options.sources" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="form.source_type !== 'manual'" label="来源ID">
        <el-input v-model.number="form.source_id as any" placeholder="事件组/告警 ID" />
      </el-form-item>
      <el-form-item label="归属项目">
        <el-input-number v-model="form.project_id as any" :min="1" placeholder="项目ID" />
      </el-form-item>
      <el-form-item label="标题">
        <el-input v-model="form.title" placeholder="派单标题" />
      </el-form-item>
      <el-form-item label="级别">
        <el-select v-model="form.level" clearable placeholder="级别" style="width: 100%">
          <el-option v-for="l in options.levels" :key="l" :label="l" :value="l" />
        </el-select>
      </el-form-item>
      <el-form-item label="根因提示">
        <el-input v-model="form.root_cause_hint" type="textarea" :rows="2" placeholder="根因提示" />
      </el-form-item>
      <el-form-item label="处理人">
        <el-select v-model="form.assignee_id as any" filterable placeholder="选择处理人" style="width: 100%">
          <el-option v-for="u in users" :key="u.id" :label="u.name" :value="u.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="处理时限">
        <el-date-picker
          v-model="form.deadline as any"
          type="datetime"
          value-format="YYYY-MM-DDTHH:mm:ss"
          placeholder="处理时限"
        />
      </el-form-item>
      <el-form-item label="处置要求">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="处置要求/说明" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">创建</el-button>
    </template>
  </el-dialog>
</template>
