import { ref } from 'vue';

export interface Task {
  id: number;
  uuid: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  error: string | null;
  result: string | null;
  params: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
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

let es: EventSource | null = null;

function handleMessage(payload: StreamPayload): void {
  if (payload.type === 'snapshot') {
    tasks.value = payload.items;
    return;
  }
  const map = new Map(tasks.value.map((t) => [t.uuid, t]));
  for (const uuid of payload.removed ?? []) {
    map.delete(uuid);
  }
  for (const item of payload.items) {
    map.set(item.uuid, { ...map.get(item.uuid), ...item });
  }
  tasks.value = [...map.values()].sort((a, b) => b.id - a.id);
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
  tasks.value = (await res.json()) as Task[];
}

export interface TaskCreatePayload {
  input: string;
  output?: string;
  quality?: number;
  container?: 'mkv' | 'mp4';
  software?: boolean;
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

export async function deleteTask(uuid: string): Promise<void> {
  const res = await fetch(`/tasks/${uuid}`, { method: 'DELETE' });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `DELETE /tasks: ${res.status}`);
  }
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
