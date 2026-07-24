<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import {
  getCorrelations,
  getCorrelationMembers,
  getCorrelationTrend,
  runCorrelations,
  type CorrelationItem,
  type CorrelationMember,
  type CorrelationTrendPoint,
} from "@/api/metrics";
import TrendLine from "@/components/TrendLine.vue";

const auth = useAuthStore();

const loading = ref(false);
const onlyCross = ref(false);
const items = ref<CorrelationItem[]>([]);
const trend = ref<CorrelationTrendPoint[]>([]);

// 成员明细懒加载缓存：groupId -> {loading, items}
const memberMap = reactive<Record<number, { loading: boolean; items: CorrelationMember[] }>>({});

const summary = computed(() => {
  const totalAlarms = items.value.reduce((s, it) => s + it.alarm_count, 0);
  const projects = new Set(items.value.map((it) => it.project_id).filter(Boolean));
  return {
    groups: items.value.length,
    cross: items.value.filter((it) => it.is_cross_device).length,
    alarms: totalAlarms,
    projects: projects.size,
  };
});

async function load() {
  loading.value = true;
  try {
    const [res, t] = await Promise.all([
      getCorrelations(onlyCross.value, 100),
      getCorrelationTrend(30, onlyCross.value).catch(() => ({ series: [] as CorrelationTrendPoint[] })),
    ]);
    items.value = res.items;
    trend.value = t.series;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载关联事件组失败");
  } finally {
    loading.value = false;
  }
}

const trendPoints = computed(() => trend.value.map((p) => ({ t: p.date, v: p.count })));

async function onRecalc() {
  loading.value = true;
  try {
    const res = await runCorrelations();
    ElMessage.success(
      `关联计算完成：事件组 ${res.groups} 个，其中跨设备 ${res.cross_device_groups} 个`,
    );
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "关联计算失败");
  } finally {
    loading.value = false;
  }
}

async function onExpand(row: CorrelationItem, expandedRows: CorrelationItem[]) {
  const isOpen = expandedRows.includes(row);
  if (!isOpen) return;
  if (memberMap[row.id]) return; // 已加载
  memberMap[row.id] = { loading: true, items: [] };
  try {
    const res = await getCorrelationMembers(row.id);
    memberMap[row.id].items = res.items;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载成员告警失败");
  } finally {
    memberMap[row.id].loading = false;
  }
}

// YYYY-MM-DDTHH:mm:ss → MM-DD HH:mm（北京墙钟直读）
function fmtTime(ts: string | null): string {
  if (!ts) return "—";
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (m) return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
  return ts;
}

function scopeText(it: CorrelationItem): string {
  if (it.spatial_type === "fence") return it.fence_name || "围栏";
  if (it.spatial_type === "geo") return `地理网格 ${it.grid_cell}`;
  return `单机 ${it.device_nos?.[0] || "?"}`;
}

function scopeTag(it: CorrelationItem): "" | "success" | "warning" | "info" {
  if (it.spatial_type === "fence") return "success";
  if (it.spatial_type === "geo") return "warning";
  return "info";
}

function scopeLabel(it: CorrelationItem): string {
  if (it.spatial_type === "fence") return "围栏";
  if (it.spatial_type === "geo") return "地理";
  return "单机";
}

function levelTag(level: string | null): "" | "danger" | "warning" | "info" {
  switch (level) {
    case "严重":
      return "danger";
    case "警告":
      return "warning";
    case "提示":
      return "info";
    default:
      return "";
  }
}

onMounted(load);
</script>

<template>
  <div class="corr-page">
    <el-card shadow="never" class="head-card">
      <div class="head">
        <div>
          <div class="title">跨设备根因关联</div>
          <div class="subtitle">
            将同项目、同空间范围（围栏 / 地理网格 / 单机）、时间近邻的告警聚合成事件组，
            揭示多台设备在同一区域短时集中告警的共因。数据每日随快照任务自动计算。
          </div>
        </div>
        <div class="actions">
          <el-switch
            v-model="onlyCross"
            active-text="仅看跨设备"
            @change="load"
          />
          <el-button
            v-if="auth.user?.is_superuser"
            type="primary"
            :loading="loading"
            @click="onRecalc"
          >
            重新计算
          </el-button>
        </div>
      </div>
      <div class="stats">
        <div class="stat">
          <div class="stat-num">{{ summary.groups }}</div>
          <div class="stat-label">事件组</div>
        </div>
        <div class="stat cross">
          <div class="stat-num">{{ summary.cross }}</div>
          <div class="stat-label">跨设备关联</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ summary.alarms }}</div>
          <div class="stat-label">涉及告警</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ summary.projects }}</div>
          <div class="stat-label">涉及项目</div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="trend-card">
      <div class="trend-head">
        <span class="card-title">关联事件组趋势（近 30 天）</span>
        <span class="trend-hint">{{ onlyCross ? "仅跨设备共因" : "全部事件组" }}</span>
      </div>
      <TrendLine
        v-if="trendPoints.length"
        :points="trendPoints"
        :height="56"
        :width="820"
        color="#e6a23c"
        :value-digits="0"
      />
      <el-empty v-else description="暂无趋势数据" :image-size="42" />
    </el-card>

    <el-card shadow="never">
      <el-table
        :data="items"
        v-loading="loading"
        border
        stripe
        style="width: 100%"
        @expand-change="onExpand"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="members">
              <div v-if="!memberMap[row.id]" class="m-empty">展开以加载成员告警…</div>
              <div v-else-if="memberMap[row.id].loading" v-loading="true" class="m-loading" />
              <template v-else>
                <el-table :data="memberMap[row.id].items" size="small" border>
                  <el-table-column prop="device_no" label="设备编号" width="150" />
                  <el-table-column prop="alarm_type" label="类型" width="140" />
                  <el-table-column prop="alarm_level" label="级别" width="90">
                    <template #default="{ row: m }">
                      <el-tag :type="levelTag(m.alarm_level)" size="small" effect="light">
                        {{ m.alarm_level || "—" }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="alarm_status" label="状态" width="100" />
                  <el-table-column prop="handle_status" label="处置" width="100" />
                  <el-table-column prop="alarm_time" label="时间" width="130">
                    <template #default="{ row: m }">{{ fmtTime(m.alarm_time) }}</template>
                  </el-table-column>
                  <el-table-column prop="alarm_info" label="信息" min-width="200" />
                </el-table>
                <div
                  v-if="memberMap[row.id].items.length === 0"
                  class="m-empty"
                >
                  无可见成员告警（可能被数据范围过滤）
                </div>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="project_name" label="项目" min-width="160" />
        <el-table-column label="空间范围" min-width="180">
          <template #default="{ row }">
            <el-tag :type="scopeTag(row)" size="small" effect="light">
              {{ scopeLabel(row) }}
            </el-tag>
            <span class="scope-text">{{ scopeText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间窗" width="170">
          <template #default="{ row }">
            {{ fmtTime(row.started_at) }} ~ {{ fmtTime(row.ended_at) }}
          </template>
        </el-table-column>
        <el-table-column label="设备数" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_cross_device" type="danger" size="small" effect="dark">
              {{ row.device_count }} 跨设备
            </el-tag>
            <span v-else>{{ row.device_count }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="alarm_count" label="告警数" width="90" align="center" />
        <el-table-column label="最高级别" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="levelTag(row.max_level)" size="small" effect="light">
              {{ row.max_level || "—" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="root_cause_hint" label="根因提示" min-width="320" show-overflow-tooltip />
        <template #empty>暂无关联事件组（近期无集中告警）</template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.corr-page {
  padding: 4px;
}
.head-card {
  margin-bottom: 12px;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.title {
  font-size: 18px;
  font-weight: 600;
}
.subtitle {
  font-size: 13px;
  color: #909399;
  margin-top: 6px;
  line-height: 1.6;
  max-width: 880px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.stats {
  display: flex;
  gap: 14px;
  margin-top: 16px;
}
.stat {
  flex: 1;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 12px 16px;
  text-align: center;
}
.stat.cross {
  background: #fef0f0;
}
.stat-num {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}
.stat.cross .stat-num {
  color: #f56c6c;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.scope-text {
  margin-left: 8px;
  font-size: 13px;
  color: #606266;
}
.members {
  padding: 8px 12px;
  background: #fafafa;
}
.m-empty {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}
.m-loading {
  height: 80px;
}
.trend-card {
  margin-bottom: 12px;
}
.trend-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 10px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.trend-hint {
  font-size: 12px;
  color: #909399;
}
</style>
