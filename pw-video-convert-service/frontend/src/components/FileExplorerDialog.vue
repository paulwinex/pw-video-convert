<template>
  <q-dialog v-model="show" persistent maximized>
    <q-card class="column full-height">
      <q-card-section class="row items-center q-py-sm">
        <div class="text-h6">Select files</div>
        <q-space />
        <div class="text-caption text-grey-7">Selected: {{ selected.length }}</div>
      </q-card-section>

      <q-separator />

      <q-card-section class="col q-pa-none">
        <FileExplorer
          ref="explorerRef"
          :mime="mime"
          height="100%"
          @update:selection="onSelection"
        />
      </q-card-section>

      <q-separator />

      <q-card-actions align="right">
        <q-btn flat label="Cancel" @click="close" />
        <q-btn
          color="primary"
          :label="`Add (${selected.length})`"
          :disable="selected.length === 0"
          @click="confirm"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import FileExplorer from './FileExplorer.vue';

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    mime?: string[];
  }>(),
  {
    mime: () => ['video/*'],
  }
);

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  confirm: [paths: string[]];
}>();

const show = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
});

const explorerRef = ref<any>(null);
const selected = ref<string[]>([]);

function onSelection(sel: { dir: string; selected: string[] }): void {
  selected.value = sel.selected;
}

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      selected.value = [];
      await nextTick();
      explorerRef.value?.refreshAll();
    }
  }
);

function close(): void {
  selected.value = [];
  show.value = false;
}

function confirm(): void {
  if (selected.value.length > 0) {
    emit('confirm', [...selected.value]);
  }
  selected.value = [];
  show.value = false;
}
</script>
