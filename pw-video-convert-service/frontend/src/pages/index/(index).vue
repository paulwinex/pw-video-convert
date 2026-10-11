<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md q-col-gutter-sm">
      <div class="col-12 col-sm-6 col-md-4">
        <q-input
          v-model="filter"
          dense
          outlined
          clearable
          debounce="150"
          placeholder="Filter by file name"
        >
          <template #prepend>
            <q-icon name="search" />
          </template>
        </q-input>
      </div>
      <q-space />
      <div class="row items-center no-wrap q-gutter-xs q-mr-md text-caption">
        <q-icon name="storage" size="18px" />
        <span v-if="disk">
          {{ disk.free_gb.toFixed(1) }} GB /
          {{ disk.total_gb.toFixed(1) }} GB
          <span class="text-grey">({{ disk.percent_used.toFixed(0) }}%)</span>
        </span>
        <span v-else>—</span>
        <span class="text-grey-5 q-mx-sm">|</span>
        <q-icon name="compress" size="18px" color="green" />
        <span>Saved: {{ fmtSize(savedSpace) }}</span>
      </div>
      <div>
        <q-btn flat round icon="menu">
          <q-menu auto-close>
            <q-list style="min-width: 280px">
              <q-item clickable v-close-popup @click="createDialog = true">
                <q-item-section avatar>
                  <q-icon name="add" />
                </q-item-section>
                <q-item-section>Create task</q-item-section>
              </q-item>
              <q-item clickable v-close-popup @click="onRefresh">
                <q-item-section avatar>
                  <q-icon name="refresh" />
                </q-item-section>
                <q-item-section>Refresh</q-item-section>
              </q-item>
              <q-separator />
              <q-item
                clickable
                v-close-popup
                :disable="!hasPending"
                @click="onPauseAll"
              >
                <q-item-section avatar>
                  <q-icon name="pause" />
                </q-item-section>
                <q-item-section>Pause all pending</q-item-section>
              </q-item>
              <q-item
                clickable
                v-close-popup
                :disable="!hasStopped"
                @click="onStartAll"
              >
                <q-item-section avatar>
                  <q-icon name="play_arrow" color="primary" />
                </q-item-section>
                <q-item-section>Start all stopped</q-item-section>
              </q-item>
              <q-item
                clickable
                v-close-popup
                :disable="!hasCompleted"
                @click="askBulkDelete('completed')"
              >
                <q-item-section avatar>
                  <q-icon name="delete" color="negative" />
                </q-item-section>
                <q-item-section>Delete completed</q-item-section>
              </q-item>
              <q-item
                clickable
                v-close-popup
                :disable="!hasFailed"
                @click="askBulkDelete('failed')"
              >
                <q-item-section avatar>
                  <q-icon name="delete" color="negative" />
                </q-item-section>
                <q-item-section>Delete all failed</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </div>
    </div>

    <q-table
      flat
      bordered
      dense
      :rows="filteredTasks"
      :columns="columns"
      row-key="uuid"
      :pagination="{ rowsPerPage: 0 }"
      hide-bottom
      no-data-label="No tasks"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <div class="row items-center no-wrap q-gutter-xs">
            <q-badge :color="statusColor(props.row.status)">
              {{ statusLabel(props.row.status) }}
            </q-badge>
            <q-icon
              v-if="props.row.status === 'failed' && props.row.error"
              name="error"
              color="negative"
              size="18px"
            >
              <q-tooltip max-width="420px">{{ props.row.error }}</q-tooltip>
            </q-icon>
          </div>
        </q-td>
      </template>

      <template #body-cell-progress="props">
        <q-td :props="props" style="width: 180px">
          <div class="row items-center no-wrap q-gutter-xs">
            <q-linear-progress
              :value="props.row.progress / 100"
              :color="progressColor(props.row.status)"
              rounded
              size="12px"
              class="col"
            />
            <div class="text-caption" style="width: 42px; text-align: right">
              {{ props.row.progress }}%
            </div>
          </div>
        </q-td>
      </template>

      <template #body-cell-duration="props">
        <q-td :props="props" class="no-wrap">{{ durationLabel(props.row) }}</q-td>
      </template>

      <template #body-cell-size="props">
        <q-td
          :props="props"
          :class="{ 'text-orange': sizeGrew(props.row) }"
          class="no-wrap"
          >{{ sizeLabel(props.row) }}</q-td
        >
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn
            v-if="props.row.status === 'pending'"
            flat
            dense
            round
            size="sm"
            icon="pause"
            @click="onPause(props.row.uuid)"
          >
            <q-tooltip>Pause — remove from queue</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.status === 'running'"
            flat
            dense
            round
            size="sm"
            icon="stop"
            color="orange"
            @click="askStop(props.row)"
          >
            <q-tooltip>Stop execution</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.status === 'paused' || props.row.status === 'canceled'"
            flat
            dense
            round
            size="sm"
            icon="play_arrow"
            color="primary"
            @click="onStart(props.row.uuid)"
          >
            <q-tooltip>Restart</q-tooltip>
          </q-btn>
          <q-btn
            flat
            dense
            round
            size="sm"
            icon="subject"
            :disable="!props.row.has_log"
            @click="onShowLog(props.row.uuid)"
          >
            <q-tooltip>
              {{ props.row.has_log ? 'Show task log' : 'Log not created yet' }}
            </q-tooltip>
          </q-btn>
          <q-btn
            flat
            dense
            round
            size="sm"
            icon="delete"
            color="negative"
            :disable="props.row.status === 'running'"
            @click="askDelete(props.row)"
          >
            <q-tooltip v-if="props.row.status === 'running'">
              Stop the task first
            </q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="logOpen" full-screen>
      <q-card class="column full-height relative-position">
        <q-bar class="bg-grey-9 text-white">
          <div class="text-subtitle2">Task log</div>
          <div class="text-caption q-ml-sm" style="font-family: monospace">
            {{ logUuid }}
          </div>
          <q-space />
          <q-btn dense flat round icon="refresh" @click="loadLog">
            <q-tooltip>Refresh</q-tooltip>
          </q-btn>
          <q-btn dense flat round icon="close" v-close-popup>
            <q-tooltip>Close</q-tooltip>
          </q-btn>
        </q-bar>

        <q-card-section class="col scroll">
          <pre class="log-pre">{{ logText }}</pre>
        </q-card-section>

        <q-inner-loading :showing="logLoading" />
      </q-card>
    </q-dialog>

    <q-dialog v-model="deleteOpen">
      <q-card style="min-width: 440px; max-width: 90vw">
        <q-card-section class="text-h6">Delete task?</q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-body2 ellipsis">{{ deleteName }}</div>
          <div class="text-caption text-grey-7 q-mt-xs">
            "Delete with result" will also remove the finished file.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn
            flat
            color="primary"
            label="Delete task"
            :loading="deleteLoading"
            @click="confirmDelete(false)"
          />
          <q-btn
            flat
            color="negative"
            label="Delete with result"
            :loading="deleteLoading"
            @click="confirmDelete(true)"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="stopOpen">
      <q-card style="min-width: 440px; max-width: 90vw">
        <q-card-section class="text-h6">Stop task?</q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-body2 ellipsis">{{ stopName }}</div>
          <div class="text-caption text-grey-7 q-mt-xs">
            Execution will be interrupted and the partial output file removed.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn
            flat
            color="negative"
            label="Stop"
            :loading="stopLoading"
            @click="confirmStop"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="bulkOpen">
      <q-card style="min-width: 460px; max-width: 90vw">
        <q-card-section class="text-h6">{{ bulkTitle }}</q-card-section>
        <q-card-section class="q-pt-none text-caption text-grey-7">
          Delete only task records or the result files as well?
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn
            flat
            color="primary"
            label="Tasks only"
            :loading="bulkLoading"
            @click="confirmBulkDelete(false)"
          />
          <q-btn
            flat
            color="negative"
            label="With result files"
            :loading="bulkLoading"
            @click="confirmBulkDelete(true)"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <CreateTaskDialog v-model="createDialog" @submit="handleCreateSubmit" ref="createDialogRef" />


  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import CreateTaskDialog from '@/components/CreateTaskDialog.vue';
import {
  createTask,
  deleteByActivity,
  deleteTask,
  fetchDisk,
  fetchLog,
  fetchTasks,
  pauseTask,
  pauseUnstarted,
  startStopped,
  startTask,
  stopTask,
  tasks,
  type DiskInfo,
  type Task,
} from '@/services/tasks';

const $q = useQuasar();

const filter = ref<string | null>('');

const filteredTasks = computed(() => {
  const q = (filter.value ?? '').trim().toLowerCase();
  if (!q) return tasks.value;
  return tasks.value.filter((t) => t.name.toLowerCase().includes(q));
});

const hasPending = computed(() =>
  tasks.value.some((t) => t.status === 'pending')
);
const hasCompleted = computed(() =>
  tasks.value.some((t) => t.status === 'completed')
);
const hasFailed = computed(() => tasks.value.some((t) => t.status === 'failed'));

const hasStopped = computed(() =>
  tasks.value.some((t) => t.status === 'paused' || t.status === 'canceled')
);

const logOpen = ref(false);
const logUuid = ref('');
const logText = ref('');
const logLoading = ref(false);

const createDialog = ref(false);
const createDialogRef = ref<any>(null);

const columns: QTableColumn<Task>[] = [
  { name: 'name', label: 'File name', field: 'name', align: 'left' },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'progress', label: 'Progress', field: 'progress', align: 'left' },
  {
    name: 'created',
    label: 'Created',
    field: 'created_at',
    align: 'left',
    format: (val) => fmtDateTime(val as string | null),
  },
  {
    name: 'started',
    label: 'Started',
    field: 'started_at',
    align: 'left',
    format: (val) => fmtDateTime(val as string | null),
  },
  {
    name: 'finished',
    label: 'Finished',
    field: 'finished_at',
    align: 'left',
    format: (val) => fmtDateTime(val as string | null),
  },
  { name: 'duration', label: 'Duration', field: 'started_at', align: 'left', style: 'min-width: 220px' },
  { name: 'size', label: 'Size', field: 'size_before', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

const now = ref(Date.now());
let tick: ReturnType<typeof setInterval> | undefined;

const disk = ref<DiskInfo | null>(null);
let diskTimer: ReturnType<typeof setInterval> | undefined;

const savedSpace = computed(() => {
  let total = 0;
  for (const t of tasks.value) {
    if (t.size_before != null && t.size_after != null) {
      total += t.size_before - t.size_after;
    }
  }
  return total;
});

async function loadDisk(): Promise<void> {
  try {
    disk.value = await fetchDisk();
  } catch (e) {
    console.error(e);
  }
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function statusColor(status: Task['status']): string {
  if (status === 'running') return 'blue';
  if (status === 'completed') return 'green';
  if (status === 'failed') return 'red';
  if (status === 'canceled') return 'orange';
  return 'grey';
}

function statusLabel(status: Task['status']): string {
  const labels: Record<Task['status'], string> = {
    pending: 'waiting',
    running: 'running',
    paused: 'paused',
    completed: 'completed',
    failed: 'failed',
    canceled: 'stopped',
  };
  return labels[status];
}

function progressColor(status: Task['status']): string {
  if (status === 'failed') return 'negative';
  if (status === 'canceled') return 'orange';
  return 'teal';
}

function fmtDateTime(value: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return (
    `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function fmtSize(bytes: number): string {
  const kib = bytes / 1024;
  if (kib >= 1024 * 1024) return `${(kib / 1024 / 1024).toFixed(1)} GiB`;
  if (kib >= 1024) return `${(kib / 1024).toFixed(1)} MiB`;
  return `${kib.toFixed(1)} KiB`;
}

function sizeLabel(row: Task): string {
  const { size_before: before, size_after: after } = row;
  if (before == null && after == null) return '—';
  if (before == null) return `… > ${fmtSize(after as number)}`;
  if (after == null) return `${fmtSize(before)} > …`;
  const pct = Math.round((after / before - 1) * 100);
  const sign = pct > 0 ? '+' : '';
  return `${fmtSize(before)} > ${fmtSize(after)} [${sign}${pct}%]`;
}

function sizeGrew(row: Task): boolean {
  const { size_before: before, size_after: after } = row;
  return before != null && after != null && after > before;
}

function fmtDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

function durationLabel(row: Task): string {
  if (!row.started_at) return '—';
  const start = new Date(row.started_at).getTime();
  if (Number.isNaN(start)) return '—';
  const end = row.finished_at ? new Date(row.finished_at).getTime() : now.value;
  const elapsed = (end - start) / 1000;
  const base = fmtDuration(elapsed);
  if (row.status === 'running' && row.progress > 0) {
    const remaining = (elapsed * (100 - row.progress)) / row.progress;
    return `${base} (~${fmtDuration(remaining)})`;
  }
  return base;
}

async function onRefresh(): Promise<void> {
  try {
    await fetchTasks();
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  }
}

const deleteOpen = ref(false);
const deleteUuid = ref('');
const deleteName = ref('');
const deleteLoading = ref(false);

function askDelete(row: Task): void {
  deleteUuid.value = row.uuid;
  deleteName.value = row.name;
  deleteOpen.value = true;
}

async function confirmDelete(withResult: boolean): Promise<void> {
  deleteLoading.value = true;
  try {
    await deleteTask(deleteUuid.value, withResult);
    await fetchTasks();
    deleteOpen.value = false;
    $q.notify({
      type: 'info',
      message: withResult ? 'Task and result deleted' : 'Task deleted',
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  } finally {
    deleteLoading.value = false;
  }
}

const stopOpen = ref(false);
const stopUuid = ref('');
const stopName = ref('');
const stopLoading = ref(false);

function askStop(row: Task): void {
  stopUuid.value = row.uuid;
  stopName.value = row.name;
  stopOpen.value = true;
}

async function confirmStop(): Promise<void> {
  stopLoading.value = true;
  try {
    await stopTask(stopUuid.value);
    await fetchTasks();
    stopOpen.value = false;
    $q.notify({ type: 'info', message: 'Task stopped' });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  } finally {
    stopLoading.value = false;
  }
}

async function onPause(uuid: string): Promise<void> {
  try {
    await pauseTask(uuid);
    await fetchTasks();
    $q.notify({ type: 'info', message: 'Task paused' });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  }
}

async function onStart(uuid: string): Promise<void> {
  try {
    await startTask(uuid);
    await fetchTasks();
    $q.notify({ type: 'info', message: 'Task started' });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  }
}

const bulkOpen = ref(false);
const bulkKind = ref<'completed' | 'failed'>('completed');
const bulkLoading = ref(false);
const bulkTitle = computed(() =>
  bulkKind.value === 'completed'
    ? 'Delete completed tasks?'
    : 'Delete failed tasks?'
);

function askBulkDelete(kind: 'completed' | 'failed'): void {
  bulkKind.value = kind;
  bulkOpen.value = true;
}

async function onPauseAll(): Promise<void> {
  try {
    const count = await pauseUnstarted();
    await fetchTasks();
    $q.notify({
      type: count ? 'info' : 'warning',
      message: count ? `Paused tasks: ${count}` : 'No pending tasks',
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  }
}

async function onStartAll(): Promise<void> {
  try {
    const count = await startStopped();
    await fetchTasks();
    $q.notify({
      type: count ? 'info' : 'warning',
      message: count ? `Started tasks: ${count}` : 'No stopped tasks',
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  }
}

async function confirmBulkDelete(withResult: boolean): Promise<void> {
  bulkLoading.value = true;
  try {
    const count = await deleteByActivity(bulkKind.value, withResult);
    await fetchTasks();
    bulkOpen.value = false;
    $q.notify({
      type: 'info',
      message: `Deleted tasks: ${count}${withResult ? ' (with files)' : ''}`,
    });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  } finally {
    bulkLoading.value = false;
  }
}

async function onShowLog(uuid: string): Promise<void> {
  logUuid.value = uuid;
  logText.value = '';
  logOpen.value = true;
  await loadLog();
}

async function loadLog(): Promise<void> {
  if (!logUuid.value) return;
  logLoading.value = true;
  try {
    logText.value = await fetchLog(logUuid.value);
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
    logOpen.value = false;
  } finally {
    logLoading.value = false;
  }
}

async function handleCreateSubmit(payloads: any[]): Promise<void> {
  try {
    for (const payload of payloads) {
      await createTask(payload);
    }
    await fetchTasks();
    createDialog.value = false;
    createDialogRef.value?.reset();
    $q.notify({ type: 'positive', message: 'Tasks created' });
  } catch (e) {
    createDialogRef.value?.setLoading(false);
    $q.notify({ type: 'negative', message: String(e) });
  }
}

onMounted(async () => {
  await onRefresh();
  void loadDisk();
  tick = setInterval(() => {
    now.value = Date.now();
  }, 1000);
  diskTimer = setInterval(loadDisk, 15000);
});

onUnmounted(() => {
  if (tick) clearInterval(tick);
  if (diskTimer) clearInterval(diskTimer);
});
</script>

<style scoped>
.log-pre {
  margin: 0;
  font-family: monospace;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
