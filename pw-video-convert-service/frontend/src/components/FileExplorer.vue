<!--
USAGE:
<file-explorer
    api-list-url="/fs"
    :mime="['video/*']"
    height="70vh"
    @update:selection="onSelection"
/>
-->
<template>
  <div class="file-explorer" :style="{ height }">
    <q-splitter
      v-model="splitterModel"
      :limits="[15, 70]"
      style="height: 100%"
    >
      <!-- ============== LEFT: folder tree ============== -->
      <template #before>
        <div class="column full-height">
          <div class="q-px-sm q-py-xs row items-center">
            <q-icon name="folder" size="18px" class="q-mr-xs" />
            <div class="text-subtitle2">Folders</div>
            <q-space />
            <q-btn
              dense flat round size="sm"
              icon="refresh"
              :loading="refreshing"
              @click="refreshAll"
            >
              <q-tooltip>Reload tree and list</q-tooltip>
            </q-btn>
          </div>
          <q-separator />

          <q-tree
            class="col scroll"
            :nodes="treeNodes"
            node-key="path"
            label-key="label"
            :expanded="expandedKeys"
            v-model:selected="selectedTreePath"
            no-selection-unset
            selected-color="primary"
            @update:expanded="onExpandedUpdate"
            @lazy-load="onLazyLoad"
          />
        </div>
      </template>

      <!-- ============== RIGHT: file list ============== -->
      <template #after>
        <div class="column full-height">
          <div class="q-px-sm q-py-xs row items-center">
            <q-icon name="insert_drive_file" size="18px" class="q-mr-xs" />
            <div class="text-subtitle2 ellipsis">
              {{ selectedDir || '~ (root)' }}
            </div>
            <q-space />
            <div class="text-caption text-grey-7">
              Selected: {{ selectedFiles.length }}
            </div>
          </div>
          <q-separator />

          <q-table
            class="col"
            flat
            bordered
            :rows="files"
            :columns="columns"
            row-key="path"
            virtual-scroll
            v-model:pagination="pagination"
            :rows-per-page-options="[0]"
            selection="multiple"
            v-model:selected="selectedFiles"
            :loading="loadingFiles"
            no-data-label="No matching files"
          >
            <template #body-cell-name="p">
              <q-td :props="p">
                <q-icon
                  name="insert_drive_file"
                  size="18px"
                  class="q-mr-xs"
                  color="blue-grey-5"
                />
                {{ p.row.name }}
              </q-td>
            </template>
          </q-table>
        </div>
      </template>
    </q-splitter>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { Notify } from 'quasar'

const props = defineProps({
  apiListUrl: { type: String, default: '/fs' },
  mime:        { type: Array,  default: () => [] },   // MIME patterns, e.g. ['video/*']
  height:      { type: String, default: '600px' }
})

const emit = defineEmits(['update:selection'])

/* ============================================================
 * API stub
 * ============================================================
 * Expected backend response shape:
 *   {
 *     path: "docs/sub",
 *     entries: [
 *       { name, path, is_dir, size, created, modified },
 *       ...
 *     ]
 *   }
 * `path` is always relative to the user root, separated by "/".
 * MIME filtering happens on the backend: folders are always returned,
 * while files are only those matching the given patterns.
 */
async function apiListDir (relPath) {
  const params = new URLSearchParams()
  params.set('path', relPath || '')
  for (const pattern of props.mime || []) {
    if (pattern) params.append('mime', pattern)
  }
  const url = `${props.apiListUrl}?${params.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${txt}`)
  }
  return await res.json()
}

/* ============================================================
 * Tree state
 * ============================================================ */
const splitterModel    = ref(30)        // tree width share, %
const treeNodes        = ref([])
const expandedKeys     = ref([])        // paths of expanded nodes
const selectedTreePath = ref(null)      // path of the selected folder
const selectedDir      = ref('')        // current folder for the right-hand list
const refreshing       = ref(false)

/* ============================================================
 * Table state
 * ============================================================ */
const files         = ref([])
const selectedFiles = ref([])
const loadingFiles  = ref(false)
const pagination    = ref({ page: 1, rowsPerPage: 0 })

const columns = [
  { name: 'name',     label: 'Name',     field: 'name',     align: 'left',  sortable: true },
  { name: 'size',     label: 'Size',     field: 'size',     align: 'right', sortable: true,
    format: (v, row) => row.is_dir || v == null ? '—' : formatSize(v) },
  { name: 'created',  label: 'Created',  field: 'created',  align: 'left',  sortable: true,
    format: v => formatDate(v) },
  { name: 'modified', label: 'Modified', field: 'modified', align: 'left',  sortable: true,
    format: v => formatDate(v) }
]

function formatSize (bytes) {
  if (bytes == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0, n = bytes
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}

function formatDate (iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return iso
  return d.toLocaleString()
}

/* ============================================================
 * Node helpers
 * ============================================================ */
function nodeFromEntry (e) {
  return {
    label: e.name,
    path:  e.path,
    isDir: e.is_dir,
    // lazy is only for folders; children load on expand
    lazy:      e.is_dir,
    children:  undefined
  }
}

/* ============================================================
 * Tree loading (one level)
 * ============================================================ */
async function loadRoot () {
  const data = await apiListDir('')
  // Root node is the user directory itself. path = ''.
  // Preload its children so the tree is not empty.
  const root = {
    label: data.path || '~',
    path:  '',
    isDir: true,
    lazy:  true,
    children: undefined
  }
  treeNodes.value = [root]
}

async function onLazyLoad ({ node, done, fail }) {
  try {
    const data = await apiListDir(node.path)
    const dirs = data.entries
      .filter(e => e.is_dir)
      .map(nodeFromEntry)
    done(dirs)
  } catch (e) {
    Notify.create({ type: 'negative', message: e.message })
    fail()
  }
}

function onExpandedUpdate (keys) {
  expandedKeys.value = keys
}

/* ============================================================
 * Folder selection — load files
 * ============================================================ */
watch(selectedTreePath, async (val) => {
  const path = val ?? ''
  selectedDir.value = path
  await loadFiles(path)
  emitSelection()
})

async function loadFiles (path) {
  loadingFiles.value = true
  try {
    const data = await apiListDir(path)
    // Show only files on the right; folder navigation happens via the tree.
    files.value = data.entries
      .filter(e => !e.is_dir)
      .map(e => ({
        name:     e.name,
        path:     e.path,
        is_dir:   e.is_dir,
        size:     e.size,
        created:  e.created,
        modified: e.modified
      }))
    // clear selection entries that are no longer present
    const allowed = new Set(files.value.map(f => f.path))
    selectedFiles.value = selectedFiles.value.filter(f => allowed.has(f.path))
  } catch (e) {
    Notify.create({ type: 'negative', message: e.message })
    files.value = []
  } finally {
    loadingFiles.value = false
  }
}

/* ============================================================
 * Exposed event and methods
 * ============================================================ */
function emitSelection () {
  emit('update:selection', getSelection())
}

function getSelection () {
  return {
    dir: selectedDir.value,
    selected: selectedFiles.value.map(f => f.path)
  }
}

watch(selectedFiles, emitSelection, { deep: true })

/* ============================================================
 * Reload: keep expanded branches and selection
 * ============================================================ */
async function refreshAll () {
  refreshing.value = true
  try {
    const expandedSnapshot = new Set(expandedKeys.value)
    const selectedSnapshot = selectedTreePath.value
    const filesSnapshot    = new Set(selectedFiles.value.map(f => f.path))

    // Rebuild the tree from the root and recursively restore
    // previously expanded branches (only those that were expanded).
    const rootData = await apiListDir('')
    const root = {
      label: rootData.path || '~',
      path:  '',
      isDir: true,
      lazy:  false,                 // loading children manually already
      children: []
    }
    await fillChildren(root, expandedSnapshot)
    treeNodes.value = [root]

    // Refresh the file list of the active folder
    if (selectedSnapshot != null) {
      await loadFiles(selectedSnapshot)
    }
    // Restore the table selection
    selectedFiles.value = files.value.filter(f => filesSnapshot.has(f.path))
    emitSelection()
  } catch (e) {
    Notify.create({ type: 'negative', message: e.message })
  } finally {
    refreshing.value = false
  }
}

async function fillChildren (node, expandedSet) {
  const data = await apiListDir(node.path)
  const children = data.entries
    .filter(e => e.is_dir)
    .map(nodeFromEntry)

  node.children = children
  for (const child of children) {
    if (expandedSet.has(child.path)) {
      await fillChildren(child, expandedSet)
      child.lazy = false  // children already loaded — lazy not needed
    }
  }
}

/* ============================================================
 * Mount
 * ============================================================ */
onMounted(async () => {
  try {
    await loadRoot()
    // Auto-select the root so the right-hand list is populated immediately
    selectedTreePath.value = ''
    expandedKeys.value = ['']
  } catch (e) {
    Notify.create({ type: 'negative', message: e.message })
  }
})

defineExpose({ getSelection, refreshAll })
</script>

<style scoped>
.file-explorer {
  border: 1px solid rgba(0, 0, 0, .12);
  border-radius: 4px;
  overflow: hidden;
}
</style>
