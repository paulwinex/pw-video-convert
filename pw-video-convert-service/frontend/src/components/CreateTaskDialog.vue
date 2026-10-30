<template>
  <q-dialog v-model="show" persistent>
    <q-card style="min-width: 600px; max-width: 90vw">
      <q-card-section>
        <div class="text-h6">Create task</div>
      </q-card-section>

      <q-card-section class="q-pt-none q-gutter-md">
        <div>
          <div class="text-subtitle2 q-mb-xs">Files (one path per line)</div>
          <q-input
            v-model="filesText"
            type="textarea"
            dense
            autogrow
            :input-style="{ minHeight: '96px', fontFamily: 'monospace' }"
            placeholder="/path/to/video1.mkv&#10;/path/to/video2.mp4"
          />
          <div class="row items-center q-mt-xs">
            <q-btn
              dense
              outline
              size="sm"
              icon="folder_open"
              label="Choose files"
              @click="browserOpen = true"
            />
            <q-space />
            <div class="text-caption text-grey-7">
              Files: {{ parsedCount }}
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

        <q-checkbox v-model="createPaused" label="Create paused" dense />

        <div v-if="inputPaths.length > 0">
          <div class="text-subtitle2 q-mb-xs">Audio tracks</div>
          <div v-for="path in inputPaths" :key="path" class="q-mb-sm">
            <div class="row items-center q-col-gutter-sm">
              <div class="col-12 col-md-5 ellipsis text-caption text-grey-5" :title="path">
                {{ baseName(path) }}
              </div>
              <div class="col-12 col-md">
                <q-select
                  v-if="(audioState[path]?.tracks?.length ?? 0) >= 2"
                  v-model="audioState[path].selected"
                  :options="audioOptions(path)"
                  :display-value="(audioState[path]?.selected ?? []).join(', ')"
                  dense
                  multiple
                  emit-value
                  map-options
                >
                  <template #option="{ itemProps, opt, selected, toggleOption }">
                    <q-item v-bind="itemProps">
                      <q-item-section>
                        <q-item-label>{{ opt.label }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <q-toggle
                          :model-value="selected"
                          @update:model-value="toggleOption(opt)"
                          dense
                        />
                      </q-item-section>
                    </q-item>
                  </template>
                </q-select>
                <div v-else class="text-caption text-grey-7">
                  <template v-if="audioState[path]?.loading">checking…</template>
                  <template v-else-if="audioState[path]?.tracks">nothing to select</template>
                  <template v-else>unavailable</template>
                </div>
              </div>
              <div class="col-auto">
                <q-btn
                  dense
                  flat
                  size="sm"
                  icon="playlist_add"
                  label="Add audio"
                  @click="openAudioPicker(path)"
                />
              </div>
            </div>
            <div v-if="(audioAdd[path] ?? []).length > 0" class="q-ml-md q-mt-xs">
              <q-chip
                v-for="(item, idx) in audioAdd[path]"
                :key="idx"
                removable
                dense
                icon="library_music"
                @remove="audioAdd[path]?.splice(idx, 1)"
              >
                [{{ item.label }}] {{ baseName(item.path) }}
              </q-chip>
            </div>
          </div>
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat label="Cancel" v-close-popup @click="close" :disable="loading" />
        <q-btn color="primary" label="Create" @click="submit" :loading="loading" />
      </q-card-actions>

      <FileExplorerDialog
        v-model="browserOpen"
        :mime="['video/*']"
        @confirm="onFilesPicked"
      />

      <FileExplorerDialog
        v-model="audioBrowserOpen"
        :mime="['audio/*']"
        @confirm="onAudioPicked"
      />
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import FileExplorerDialog from './FileExplorerDialog.vue';
import { probeFile, type AudioTrack, type AudioAdd } from '@/services/tasks';

const REMAP_PATH = '/mnt/NAS';

interface FileAudioState {
  tracks: AudioTrack[] | null;
  selected: number[];
  loading: boolean;
}

const $q = useQuasar();

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
const audioBrowserOpen = ref(false);
const audioPickFor = ref<string | null>(null);
const quality = ref(5);
const output = ref('');
const resolution = ref('original');
const createPaused = ref(false);
const loading = ref(false);
const audioState = ref<Record<string, FileAudioState>>({});
const audioAdd = ref<Record<string, AudioAdd[]>>({});

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

function baseName(path: string): string {
  return path.split('/').pop() ?? path;
}

function trackLabel(t: AudioTrack): string {
  const parts = [`#${t.track}`];
  if (t.language) parts.push(t.language);
  if (t.title) parts.push(t.title);
  parts.push(t.codec);
  parts.push(`${t.channels}ch`);
  return parts.join(' · ');
}

function audioOptions(path: string): { label: string; value: number }[] {
  return (audioState.value[path]?.tracks ?? []).map((t) => ({
    label: trackLabel(t),
    value: t.track,
  }));
}

async function runProbes(paths: string[]): Promise<void> {
  const queue = [...paths];
  const worker = async (): Promise<void> => {
    while (queue.length > 0) {
      const path = queue.shift();
      if (!path) return;
      try {
        const tracks = await probeFile(path, REMAP_PATH);
        if (!(path in audioState.value)) continue;
        audioState.value[path] = {
          tracks,
          selected: tracks.map((t) => t.track),
          loading: false,
        };
      } catch {
        if (path in audioState.value) {
          audioState.value[path] = { tracks: null, selected: [], loading: false };
        }
      }
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(4, queue.length) }, worker)
  );
}

function syncAudioProbes(): void {
  const paths = parseFiles(filesText.value);
  for (const key of Object.keys(audioState.value)) {
    if (!paths.includes(key)) delete audioState.value[key];
  }
  for (const key of Object.keys(audioAdd.value)) {
    if (!paths.includes(key)) delete audioAdd.value[key];
  }
  const missing = paths.filter((p) => !(p in audioState.value));
  if (missing.length === 0) return;
  for (const p of missing) {
    audioState.value[p] = { tracks: null, selected: [], loading: true };
  }
  void runProbes(missing);
}

let probeTimer: ReturnType<typeof setTimeout> | null = null;
watch(filesText, () => {
  if (probeTimer) clearTimeout(probeTimer);
  probeTimer = setTimeout(syncAudioProbes, 500);
});

const inputPaths = computed(() => parseFiles(filesText.value));

function openAudioPicker(path: string): void {
  audioPickFor.value = path;
  audioBrowserOpen.value = true;
}

function promptLabel(fileName: string): Promise<string | null> {
  return new Promise((resolve) => {
    $q.dialog({
      title: 'Audio track label',
      message: `How to label the audio track from "${fileName}"?`,
      prompt: {
        model: '',
        type: 'text',
        isValid: (v: string) => v.trim().length > 0,
      },
      cancel: true,
    })
      .onOk((label: string) => resolve(label))
      .onCancel(() => resolve(null));
  });
}

async function onAudioPicked(paths: string[]): Promise<void> {
  const target = audioPickFor.value;
  audioPickFor.value = null;
  if (!target) return;
  const existing = audioAdd.value[target] ?? [];
  for (const raw of paths) {
    const path = raw.trim();
    if (!path || existing.some((a) => a.path === path)) continue;
    const label = await promptLabel(baseName(path));
    if (label === null) continue;
    existing.push({ path, label: label.trim() });
  }
  if (existing.length > 0) {
    audioAdd.value[target] = existing;
  }
}

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
  createPaused.value = false;
  loading.value = false;
  audioState.value = {};
  audioAdd.value = {};
  audioPickFor.value = null;
  audioBrowserOpen.value = false;
  if (probeTimer) {
    clearTimeout(probeTimer);
    probeTimer = null;
  }
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
    errors.push('Specify at least one file path');
  }
  const v = validateOutput(output.value);
  if (!v.ok) {
    errors.push(v.error || 'Invalid output');
  }
  for (const input of inputs) {
    const state = audioState.value[input];
    if (state?.tracks && state.tracks.length >= 2 && state.selected.length === 0) {
      errors.push(`${baseName(input)}: keep at least one audio track`);
    }
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
        remap_path: REMAP_PATH,
      };
      if (resolution.value !== 'original') {
        const parts = (resolution.value as string).split(',');
        const w = parseInt(parts[0] ?? '0');
        const h = parseInt(parts[1] ?? '0');
        if (!isNaN(w) && !isNaN(h)) {
          payload.resolution = [w, h];
        }
      }
      const state = audioState.value[input];
      if (state?.tracks && state.selected.length < state.tracks.length) {
        payload.audio = [...state.selected].sort((a, b) => a - b);
      }
      if ((audioAdd.value[input] ?? []).length > 0) {
        payload.audio_add = audioAdd.value[input];
      }
      if (createPaused.value) {
        payload.paused = true;
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
