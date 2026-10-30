import { ref } from 'vue';

export interface Task {
  id: number;
  uuid: string;
  name: string;
  status:
    | 'pending'
    | 'running'
    | 'paused'
    | 'completed'
    | 'failed'
    | 'canceled';
  queue_order: number | null;
  progress: number;
  error: string | null;
  result: string | null;
  params: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  size_before: number | null;
  size_after: number | null;
  has_log: boolean;
}

interface SnapshotPayload {
  type: 'snapshot';
  items: Task[];
}

interface UpdatePayload {
  type: 'update';
  items: Task[];
  removed?: string[];
}

type StreamPayload = SnapshotPayload | UpdatePayload;

export const sseConnected = ref(false);
export const tasks = ref<Task[]>([]);

// Mirror of the backend order: list position (queue_order) descending —
// new tasks land on top, the bottom-most pending row runs next.
export function compareTasks(a: Task, b: Task): number {
  const qa = a.queue_order ?? -Number.MAX_SAFE_INTEGER;
  const qb = b.queue_order ?? -Number.MAX_SAFE_INTEGER;
  return qb - qa || b.id - a.id;
}

let es: EventSource | null = null;

function handleMessage(payload: StreamPayload): void {
  if (payload.type === 'snapshot') {
    tasks.value = [...payload.items].sort(compareTasks);
    return;
  }
  const map = new Map(tasks.value.map((t) => [t.uuid, t]));
  for (const uuid of payload.removed ?? []) {
    map.delete(uuid);
  }
  for (const item of payload.items) {
    map.set(item.uuid, { ...map.get(item.uuid), ...item });
  }
  tasks.value = [...map.values()].sort(compareTasks);
}

export function startTaskStream(): void {
  if (es) return;
  es = new EventSource('/tasks/stream');
  es.addEventListener('open', () => (sseConnected.value = true));
  es.addEventListener('error', () => (sseConnected.value = false));
  es.addEventListener('tasks', (ev) => {
    try {
      handleMessage(JSON.parse((ev as MessageEvent).data) as StreamPayload);
    } catch (e) {
      console.error('SSE parse error', e);
    }
  });
}

export function stopTaskStream(): void {
  es?.close();
  es = null;
  sseConnected.value = false;
}

export async function fetchTasks(): Promise<void> {
  const res = await fetch('/tasks');
  if (!res.ok) throw new Error(`GET /tasks: ${res.status}`);
  tasks.value = ((await res.json()) as Task[]).sort(compareTasks);
}

export async function reorderTasks(uuids: string[]): Promise<number> {
  const res = await fetch('/tasks/reorder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uuids }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(
      typeof body?.detail === 'string'
        ? body.detail
        : `POST /tasks/reorder: ${res.status}`
    );
  }
  return ((await res.json()) as { count: number }).count;
}

export interface AudioTrack {
  track: number;
  index: number | null;
  codec: string;
  channels: number;
  language: string | null;
  title: string | null;
  stream_bitrate: number | null;
}

export async function probeFile(
  input: string,
  remapPath?: string | null
): Promise<AudioTrack[]> {
  const params = new URLSearchParams({ path: input });
  if (remapPath) params.set('remap_path', remapPath);
  const res = await fetch(`/probe?${params.toString()}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(
      typeof body?.detail === 'string' ? body.detail : `GET /probe: ${res.status}`
    );
  }
  return ((await res.json()) as { audio: AudioTrack[] }).audio;
}

export interface AudioAdd {
  path: string;
  label: string;
}

export interface TaskCreatePayload {
  input: string;
  output?: string;
  quality?: number;
  container?: 'mkv' | 'mp4';
  software?: boolean;
  resolution?: [number, number];
  audio?: number[];
  audio_add?: AudioAdd[];
  paused?: boolean;
  remap_path?: string | null;
}

export async function createTask(payload: TaskCreatePayload): Promise<void> {
  const res = await fetch('/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(
      typeof body?.detail === 'string'
        ? body.detail
        : `POST /tasks: ${res.status}`
    );
  }
}

export async function deleteTask(
  uuid: string,
  withResult = false
): Promise<void> {
  const query = withResult ? '?with_result=true' : '';
  const res = await fetch(`/tasks/${uuid}${query}`, { method: 'DELETE' });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `DELETE /tasks: ${res.status}`);
  }
}

async function postTaskAction(
  uuid: string,
  action: 'pause' | 'start' | 'stop'
): Promise<void> {
  const res = await fetch(`/tasks/${uuid}/${action}`, { method: 'POST' });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `POST /tasks/${uuid}/${action}: ${res.status}`);
  }
}

export function pauseTask(uuid: string): Promise<void> {
  return postTaskAction(uuid, 'pause');
}

export function startTask(uuid: string): Promise<void> {
  return postTaskAction(uuid, 'start');
}

export function stopTask(uuid: string): Promise<void> {
  return postTaskAction(uuid, 'stop');
}

export async function pauseUnstarted(): Promise<number> {
  const res = await fetch('/tasks/pause-unstarted', { method: 'POST' });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `POST /tasks/pause-unstarted: ${res.status}`);
  }
  return ((await res.json()) as { count: number }).count;
}

export async function startStopped(): Promise<number> {
  const res = await fetch('/tasks/start-stopped', { method: 'POST' });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `POST /tasks/start-stopped: ${res.status}`);
  }
  return ((await res.json()) as { count: number }).count;
}

export async function deleteByActivity(
  kind: 'completed' | 'failed',
  withResult = false
): Promise<number> {
  const query = withResult ? '?with_result=true' : '';
  const res = await fetch(`/tasks/${kind}${query}`, { method: 'DELETE' });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `DELETE /tasks/${kind}: ${res.status}`);
  }
  return ((await res.json()) as { count: number }).count;
}

export async function fetchLog(uuid: string): Promise<string> {
  const res = await fetch(`/tasks/${uuid}/log`);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `GET log: ${res.status}`);
  }
  return res.text();
}

export interface DiskInfo {
  path: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  total_gb: number;
  used_gb: number;
  free_gb: number;
  percent_used: number;
}

export async function fetchDisk(): Promise<DiskInfo> {
  const res = await fetch('/system/disk');
  if (!res.ok) throw new Error(`GET /system/disk: ${res.status}`);
  return (await res.json()) as DiskInfo;
}
