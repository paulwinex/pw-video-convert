<template>
  <q-layout view="hHh lpR fFf">
    <q-header class="bg-grey-9 text-white" >
      <q-toolbar>
        <q-toolbar-title>pwConvert</q-toolbar-title>
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
import { onMounted, onUnmounted } from 'vue';
import {
  sseConnected,
  startTaskStream,
  stopTaskStream,
} from '@/services/tasks';

onMounted(() => {
  startTaskStream();
});

onUnmounted(() => {
  stopTaskStream();
});
</script>
