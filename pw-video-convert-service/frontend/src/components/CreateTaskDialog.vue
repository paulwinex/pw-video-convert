<template>
  <q-dialog v-model="show" persistent>
    <q-card style="min-width: 600px; max-width: 90vw">
      <q-card-section>
        <div class="text-h6">Создать задачу</div>
      </q-card-section>

      <q-card-section class="q-pt-none q-gutter-md">
        <div>
          <div class="text-subtitle2 q-mb-xs">Files (один путь в строке)</div>
          <q-input
            v-model="filesText"
            type="textarea"
            dense
            autogrow
            :input-style="{ minHeight: '96px', fontFamily: 'monospace' }"
            placeholder="/путь/к/видео1.mkv&#10;/путь/к/видео2.mp4"
          />
          <div class="row items-center q-mt-xs">
            <q-btn
              dense
              outline
              size="sm"
              icon="folder_open"
              label="Выбрать файлы"
              @click="browserOpen = true"
            />
            <q-space />
            <div class="text-caption text-grey-7">
              Файлов: {{ parsedCount }}
            </div>
          </div>
        </div>

        <div>
          <div class="text-subtitle2 q-mb-xs">Quality: {{ quality }}</div>
          <q-slider v-model="quality" :min="1" :max="10" :step="1" snap />
        </div>

        <div>
          <div class="text-subtitle2 q-mb-xs">Output (subfolder, relative)</div>
          <q-input v-model="output" dense placeholder="optional, leave empty for default" />
        </div>

        <div>
          <div class="text-subtitle2 q-mb-xs">Resolution</div>
          <q-select v-model="resolution" :options="resolutionOptions" dense emit-value map-options />
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat label="Отмена" v-close-popup @click="close" :disable="loading" />
        <q-btn color="primary" label="Создать" @click="submit" :loading="loading" />
      </q-card-actions>

      <FileExplorerDialog
        v-model="browserOpen"
        :mime="['video/*']"
        @confirm="onFilesPicked"
      />
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import FileExplorerDialog from './FileExplorerDialog.vue';

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  submit: [payloads: any[]];
}>();

const show = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
});

const filesText = ref('');
const browserOpen = ref(false);
const quality = ref(5);
const output = ref('');
const resolution = ref('original');
const loading = ref(false);

const resolutionOptions = [
  { label: 'Original', value: 'original' },
  { label: '2K (2560x1440)', value: '2560,1440' },
  { label: 'Full HD (1920x1080)', value: '1920,1080' },
  { label: 'HD (1280x720)', value: '1280,720' },
];

function parseFiles(text: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const line of text.split('\n')) {
    const path = line.trim();
    if (path && !seen.has(path)) {
      seen.add(path);
      result.push(path);
    }
  }
  return result;
}

const parsedCount = computed(() => parseFiles(filesText.value).length);

function onFilesPicked(paths: string[]): void {
  const merged = parseFiles(filesText.value);
  const seen = new Set(merged);
  for (const raw of paths) {
    const path = raw.trim();
    if (path && !seen.has(path)) {
      seen.add(path);
      merged.push(path);
    }
  }
  filesText.value = merged.join('\n');
}

function reset() {
  filesText.value = '';
  quality.value = 5;
  output.value = '';
  resolution.value = 'original';
  loading.value = false;
}

function close() {
  show.value = false;
  reset();
}

function validateOutput(text: string): { ok: boolean; error?: string } {
  const t = text.trim();
  if (!t) return { ok: true };
  if (t.startsWith('~')) return { ok: false, error: "Output must not contain '~'" };
  if (t.startsWith('/')) return { ok: false, error: 'Output must be a relative path' };
  if (t.length >= 2 && t[1] === ':') return { ok: false, error: 'Output must be a relative path' };
  return { ok: true };
}

async function submit() {
  const errors: string[] = [];
  const inputs = parseFiles(filesText.value);
  if (inputs.length === 0) {
    errors.push('Укажите хотя бы один путь к файлу');
  }
  const v = validateOutput(output.value);
  if (!v.ok) {
    errors.push(v.error || 'Invalid output');
  }
  if (errors.length > 0) {
    return Promise.reject(new Error(errors.join('\n')));
  }

  loading.value = true;
  const payloads: any[] = [];
  try {
    for (const input of inputs) {
      const payload: any = {
        input,
        quality: quality.value,
        output: output.value.trim() ? output.value.trim() : undefined,
        remap_path: '/mnt/NAS',
      };
      if (resolution.value !== 'original') {
        const parts = (resolution.value as string).split(',');
        const w = parseInt(parts[0] ?? '0');
        const h = parseInt(parts[1] ?? '0');
        if (!isNaN(w) && !isNaN(h)) {
          payload.resolution = [w, h];
        }
      }
      payloads.push(payload);
    }
    emit('submit', payloads);
  } finally {
    loading.value = false;
  }
}

defineExpose({ reset, setLoading: (val: boolean) => (loading.value = val) });
</script>
