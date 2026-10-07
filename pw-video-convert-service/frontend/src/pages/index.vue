<template>
  <q-layout view="hHh lpR fFf">
    <q-header class="bg-grey-9 text-white" >
      <q-toolbar>
        <q-toolbar-title>pwConvert</q-toolbar-title>
        <div class="text-caption q-mr-md">
          Disk free:
          <b>{{ disk?.free_gb ?? '—' }}</b> GB / {{ disk?.total_gb ?? '—' }} GB
          <template v-if="disk">({{ disk.percent_used }}%)</template>
        </div>
        <q-badge round :color="sseConnected ? 'positive' : 'negative'">
          <q-tooltip>SSE: {{ sseConnected ? 'connected' : 'disconnected' }}</q-tooltip>
        </q-badge>
      </q-toolbar>
    </q-header>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import {
  fetchDisk,
  sseConnected,
  startTaskStream,
  stopTaskStream,
  type DiskInfo,
} from '@/services/tasks';

const disk = ref<DiskInfo | null>(null);

async function loadDisk(): Promise<void> {
  try {
    disk.value = await fetchDisk();
  } catch (e) {
    console.error(e);
  }
}

let diskTimer: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  startTaskStream();
  void loadDisk();
  diskTimer = setInterval(loadDisk, 15000);
});

onUnmounted(() => {
  stopTaskStream();
  if (diskTimer) clearInterval(diskTimer);
});
</script>
