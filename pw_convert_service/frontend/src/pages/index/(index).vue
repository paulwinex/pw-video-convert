<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md q-col-gutter-sm">
      <div class="text-h6">Очередь задач</div>
      <q-space />
      <div>
        <q-input
          v-model.number="duration"
          type="number"
          label="duration_sec"
          dense
          outlined
          :min="1"
          style="width: 130px"
        />
      </div>
      <div>
        <q-input
          v-model="failAt"
          type="number"
          label="fail_at (5-95)"
          dense
          outlined
          clearable
          style="width: 150px"
        />
      </div>
      <div>
        <q-btn
          color="primary"
          unelevated
          label="Создать задачу"
          :loading="creating"
          @click="onCreate"
        />
      </div>
      <div>
        <q-btn flat round icon="refresh" @click="onRefresh" />
      </div>
    </div>

    <q-table
      flat
      bordered
      :rows="tasks"
      :columns="columns"
      row-key="uuid"
      :pagination="{ rowsPerPage: 10 }"
      no-data-label="Задач нет"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.row.status)">
            {{ statusLabel(props.row.status) }}
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-progress="props">
        <q-td :props="props" style="width: 200px">
          <q-linear-progress
            :value="props.row.progress / 100"
            :color="props.row.status === 'failed' ? 'negative' : 'teal'"
            rounded
            size="16px"
          />
          <div class="text-caption">{{ props.row.progress }}%</div>
        </q-td>
      </template>

      <template #body-cell-meta="props">
        <q-td :props="props" style="max-width: 380px">
          <div class="text-caption">
            created: {{ fmt(props.row.created_at) }}
            <template v-if="props.row.started_at">
              | started: {{ fmt(props.row.started_at) }}
            </template>
            <template v-if="props.row.finished_at">
              | finished: {{ fmt(props.row.finished_at) }}
            </template>
          </div>
          <div
            v-if="props.row.error"
            class="text-negative text-caption ellipsis"
            :title="props.row.error"
          >
            {{ props.row.error }}
          </div>
          <div
            v-else-if="props.row.result"
            class="text-positive text-caption ellipsis"
            :title="props.row.result"
          >
            {{ props.row.result }}
          </div>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn
            flat
            dense
            round
            icon="subject"
            :disable="!props.row.has_log"
            @click="onShowLog(props.row.uuid)"
          >
            <q-tooltip>
              {{ props.row.has_log ? 'Показать лог задачи' : 'Лог ещё не создан' }}
            </q-tooltip>
          </q-btn>
          <q-btn
            flat
            dense
            round
            icon="delete"
            color="negative"
            :disable="props.row.status === 'running'"
            @click="onDelete(props.row.uuid)"
          >
            <q-tooltip v-if="props.row.status === 'running'">
              Выполняющуюся задачу удалить нельзя
            </q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="logOpen" full-screen>
      <q-card class="column full-height relative-position">
        <q-bar class="bg-grey-9 text-white">
          <div class="text-subtitle2">Лог задачи</div>
          <div class="text-caption q-ml-sm" style="font-family: monospace">
            {{ logUuid }}
          </div>
          <q-space />
          <q-btn dense flat round icon="refresh" @click="loadLog">
            <q-tooltip>Обновить</q-tooltip>
          </q-btn>
          <q-btn dense flat round icon="close" v-close-popup>
            <q-tooltip>Закрыть</q-tooltip>
          </q-btn>
        </q-bar>

        <q-card-section class="col scroll">
          <pre class="log-pre">{{ logText }}</pre>
        </q-card-section>

        <q-inner-loading :showing="logLoading" />
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import {
  createTask,
  deleteTask,
  fetchLog,
  fetchTasks,
  tasks,
  type Task,
} from '@/services/tasks';

const $q = useQuasar();

const duration = ref(10);
const failAt = ref<number | null>(null);
const creating = ref(false);

const logOpen = ref(false);
const logUuid = ref('');
const logText = ref('');
const logLoading = ref(false);

const columns: QTableColumn<Task>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left' },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'progress', label: 'Progress', field: 'progress', align: 'left' },
  { name: 'meta', label: 'Meta', field: 'id', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

function statusColor(status: Task['status']): string {
  if (status === 'running') return 'blue';
  if (status === 'completed') return 'green';
  if (status === 'failed') return 'red';
  return 'grey';
}

function statusLabel(status: Task['status']): string {
  const labels: Record<Task['status'], string> = {
    pending: 'ожидание',
    running: 'в работе',
    completed: 'завершено',
    failed: 'ошибка',
  };
  return labels[status];
}

function fmt(value: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

async function onRefresh(): Promise<void> {
  try {
    await fetchTasks();
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  }
}

async function onCreate(): Promise<void> {
  creating.value = true;
  try {
    const fa =
      failAt.value === null || Number.isNaN(Number(failAt.value))
        ? null
        : Number(failAt.value);
    await createTask(duration.value, fa);
    $q.notify({ type: 'positive', message: 'Задача создана' });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
  } finally {
    creating.value = false;
  }
}

async function onDelete(uuid: string): Promise<void> {
  try {
    await deleteTask(uuid);
    await fetchTasks();
    $q.notify({ type: 'info', message: 'Задача удалена' });
  } catch (e) {
    $q.notify({ type: 'negative', message: String(e) });
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

onMounted(async () => {
  await onRefresh();
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
