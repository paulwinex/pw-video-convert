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
      <!-- ============== ЛЕВО: дерево каталогов ============== -->
      <template #before>
        <div class="column full-height">
          <div class="q-px-sm q-py-xs row items-center">
            <q-icon name="folder" size="18px" class="q-mr-xs" />
            <div class="text-subtitle2">Каталоги</div>
            <q-space />
            <q-btn
              dense flat round size="sm"
              icon="refresh"
              :loading="refreshing"
              @click="refreshAll"
            >
              <q-tooltip>Перезагрузить дерево и список</q-tooltip>
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

      <!-- ============== ПРАВО: список файлов ============== -->
      <template #after>
        <div class="column full-height">
          <div class="q-px-sm q-py-xs row items-center">
            <q-icon name="insert_drive_file" size="18px" class="q-mr-xs" />
            <div class="text-subtitle2 ellipsis">
              {{ selectedDir || '~ (корень)' }}
            </div>
            <q-space />
            <div class="text-caption text-grey-7">
              Выбрано: {{ selectedFiles.length }}
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
            no-data-label="Нет подходящих файлов"
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
  mime:        { type: Array,  default: () => [] },   // MIME-паттерны, напр. ['video/*']
  height:      { type: String, default: '600px' }
})

const emit = defineEmits(['update:selection'])

/* ============================================================
 * API stub
 * ============================================================
 * Ждём от бэкенда ответ вида:
 *   {
 *     path: "docs/sub",
 *     entries: [
 *       { name, path, is_dir, size, created, modified },
 *       ...
 *     ]
 *   }
 * `path` всегда относительный от корня пользователя, разделитель "/".
 * Фильтрация по mime выполняется на бэкенде: каталоги приходят всегда,
 * а файлы — только те, что подходят под переданные паттерны.
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
 * Состояние дерева
 * ============================================================ */
const splitterModel    = ref(30)        // доля ширины дерева, %
const treeNodes        = ref([])
const expandedKeys     = ref([])        // массив path раскрытых узлов
const selectedTreePath = ref(null)      // path выделенного каталога
const selectedDir      = ref('')        // текущая папка для списка справа
const refreshing       = ref(false)

/* ============================================================
 * Состояние таблицы
 * ============================================================ */
const files         = ref([])
const selectedFiles = ref([])
const loadingFiles  = ref(false)
const pagination    = ref({ page: 1, rowsPerPage: 0 })

const columns = [
  { name: 'name',     label: 'Имя',      field: 'name',     align: 'left',  sortable: true },
  { name: 'size',     label: 'Размер',   field: 'size',     align: 'right', sortable: true,
    format: (v, row) => row.is_dir || v == null ? '—' : formatSize(v) },
  { name: 'created',  label: 'Создан',   field: 'created',  align: 'left',  sortable: true,
    format: v => formatDate(v) },
  { name: 'modified', label: 'Изменён',  field: 'modified', align: 'left',  sortable: true,
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
 * Утилиты построения узлов
 * ============================================================ */
function nodeFromEntry (e) {
  return {
    label: e.name,
    path:  e.path,
    isDir: e.is_dir,
    // lazy только для каталогов; дети подгрузятся при раскрытии
    lazy:      e.is_dir,
    children:  undefined
  }
}

/* ============================================================
 * Загрузка дерева (один уровень)
 * ============================================================ */
async function loadRoot () {
  const data = await apiListDir('')
  // Корневой узел — сам каталог пользователя. path = ''.
  // У него сразу подгрузим детей, чтобы дерево не было пустым.
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
 * Выбор каталога — грузим файлы
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
    // Справа показываем только файлы; навигация по каталогам — через дерево.
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
    // очищаем выбор, если старая выборка не пересекается
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
 * Наружу — событие и методы
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
 * Перезагрузка: сохранить раскрытые ветки и выбор
 * ============================================================ */
async function refreshAll () {
  refreshing.value = true
  try {
    const expandedSnapshot = new Set(expandedKeys.value)
    const selectedSnapshot = selectedTreePath.value
    const filesSnapshot    = new Set(selectedFiles.value.map(f => f.path))

    // Пересобираем дерево, начиная с корня, и рекурсивно
    // восстанавливаем раскрытые ветки (только те, что были раскрыты).
    const rootData = await apiListDir('')
    const root = {
      label: rootData.path || '~',
      path:  '',
      isDir: true,
      lazy:  false,                 // уже загружаем детей вручную
      children: []
    }
    await fillChildren(root, expandedSnapshot)
    treeNodes.value = [root]

    // Обновляем список файлов активной папки
    if (selectedSnapshot != null) {
      await loadFiles(selectedSnapshot)
    }
    // Восстанавливаем выделение в таблице
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
      child.lazy = false  // дети уже загружены — lazy не нужен
    }
  }
}

/* ============================================================
 * Mount
 * ============================================================ */
onMounted(async () => {
  try {
    await loadRoot()
    // Автовыбор корня, чтобы справа сразу был список
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
