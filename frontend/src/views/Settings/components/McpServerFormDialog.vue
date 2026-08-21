<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑 MCP 服务器' : '添加 MCP 服务器'"
    width="640px"
    :close-on-click-modal="false"
    align-center
    @closed="resetForm"
  >
    <div class="form-body">
      <!-- 通用字段 -->
      <div class="form-row">
        <div class="form-item">
          <label class="form-label">名称 <span class="required">*</span></label>
          <el-input v-model="form.name" placeholder="如 filesystem" :disabled="isEdit" />
        </div>
        <div class="form-item">
          <label class="form-label">类型</label>
          <el-radio-group v-model="form.type">
            <el-radio-button value="stdio">stdio</el-radio-button>
            <el-radio-button value="streamable-http">streamable-http</el-radio-button>
            <el-radio-button value="sse">sse</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <div class="form-item">
        <label class="form-label">描述</label>
        <el-input v-model="form.description" placeholder="可选" maxlength="500" />
      </div>

      <!-- stdio 分支 -->
      <template v-if="form.type === 'stdio'">
        <div class="form-item">
          <label class="form-label">命令 <span class="required">*</span></label>
          <div class="command-row">
            <el-autocomplete
              v-model="form.command"
              :fetch-suggestions="suggestCommands"
              placeholder="如 uvx / npx / python / docker"
              style="flex: 1"
            />
            <el-button :loading="runtimeChecking" @click="doCheckRuntime">检测运行时</el-button>
            <el-button
              v-if="runtimeResult && !runtimeResult.command_available && runtimeResult.install_hint === 'uv'"
              type="primary"
              :loading="installingTool"
              @click="doInstallUv"
            >一键安装 uv</el-button>
          </div>
          <div v-if="runtimeResult" class="runtime-result" :class="runtimeResult.command_available ? 'ok' : 'fail'">
            <template v-if="runtimeResult.command_available">
              ✓ 命令可用{{ runtimeResult.resolved_command ? `（${runtimeResult.resolved_command}）` : '' }}
              <span v-if="runtimeResult.python_version"> · Python {{ runtimeResult.python_version }}</span>
            </template>
            <template v-else>✗ {{ runtimeResult.error }}</template>
          </div>
        </div>

        <div class="form-item">
          <label class="form-label">参数（args）</label>
          <div v-for="(_arg, index) in form.args" :key="index" class="kv-row">
            <el-input v-model="form.args[index]" placeholder="参数" />
            <el-button text type="danger" @click="form.args.splice(index, 1)">删除</el-button>
          </div>
          <el-button text type="primary" @click="form.args.push('')">+ 添加参数</el-button>
        </div>

        <div class="form-item">
          <label class="form-label">环境变量（env）</label>
          <div v-for="(row, index) in envRows" :key="index" class="kv-row">
            <el-input v-model="row.key" placeholder="变量名" style="flex: 1" />
            <el-input v-model="row.value" placeholder="值（支持 ${VAR} 展开）" style="flex: 1" />
            <el-button text type="danger" @click="envRows.splice(index, 1)">删除</el-button>
          </div>
          <el-button text type="primary" @click="envRows.push({ key: '', value: '' })">+ 添加变量</el-button>
        </div>

        <div class="form-item">
          <label class="form-label">Python 依赖（deps，安装到容器环境）</label>
          <div v-for="(_dep, index) in form.deps" :key="index" class="kv-row">
            <el-input v-model="form.deps[index]" placeholder="如 pandas>=2.0" />
            <el-button text type="danger" @click="form.deps.splice(index, 1)">删除</el-button>
          </div>
          <el-button text type="primary" @click="form.deps.push('')">+ 添加依赖</el-button>
        </div>
      </template>

      <!-- http / sse 分支 -->
      <template v-else>
        <div class="form-item">
          <label class="form-label">URL <span class="required">*</span></label>
          <el-input v-model="form.url" placeholder="https://example.com/mcp" />
        </div>

        <div class="form-item">
          <label class="form-label">请求头（headers）</label>
          <div v-for="(row, index) in headerRows" :key="index" class="kv-row">
            <el-input v-model="row.key" placeholder="Header 名" style="flex: 1" />
            <el-input v-model="row.value" placeholder="值（支持 ${VAR} 展开）" style="flex: 1" />
            <el-button text type="danger" @click="headerRows.splice(index, 1)">删除</el-button>
          </div>
          <el-button text type="primary" @click="headerRows.push({ key: '', value: '' })">+ 添加 Header</el-button>
        </div>

        <el-alert
          v-if="form.type === 'sse'"
          type="warning"
          :closable="false"
          show-icon
          title="SSE 为旧版传输协议，仅作兼容支持；如服务端支持 streamable-http 建议优先使用"
        />
      </template>

      <div class="dialog-warning">
        <el-icon><Warning /></el-icon> 配置前请确认来源，甄别风险
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="confirmSave">
        {{ isEdit ? '保存' : '添加' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Warning } from '@element-plus/icons-vue'
import { useMCPStore } from '@/stores/mcp'
import type { MCPServerConfig, MCPServerType, RuntimeCheckResult } from '@/types/mcp'

const COMMON_COMMANDS = ['uvx', 'npx', 'python', 'python3', 'node', 'docker']

const mcpStore = useMCPStore()
const visible = defineModel<boolean>({ default: false })

const props = defineProps<{
  /** 编辑模式：传入服务器名与现有配置 */
  editName?: string
  editConfig?: MCPServerConfig
}>()

const emit = defineEmits<{ saved: [] }>()

const isEdit = computed(() => Boolean(props.editName))

const saving = ref(false)
const runtimeChecking = ref(false)
const installingTool = ref(false)
const runtimeResult = ref<RuntimeCheckResult | null>(null)

const form = ref<{
  name: string
  type: MCPServerType
  description: string
  command: string
  args: string[]
  deps: string[]
  url: string
}>({
  name: '',
  type: 'stdio',
  description: '',
  command: '',
  args: [],
  deps: [],
  url: ''
})

const envRows = ref<{ key: string; value: string }[]>([])
const headerRows = ref<{ key: string; value: string }[]>([])

watch(visible, (val) => {
  if (val) {
    if (props.editName && props.editConfig) {
      const cfg = props.editConfig
      form.value = {
        name: props.editName,
        type: (cfg.type as MCPServerType) || 'stdio',
        description: cfg.description || '',
        command: cfg.command || '',
        args: [...(cfg.args || [])],
        deps: [...(cfg.deps || [])],
        url: cfg.url || ''
      }
      envRows.value = Object.entries(cfg.env || {}).map(([key, value]) => ({ key, value }))
      headerRows.value = Object.entries(cfg.headers || {}).map(([key, value]) => ({ key, value }))
    }
    runtimeResult.value = null
  }
})

const resetForm = () => {
  form.value = { name: '', type: 'stdio', description: '', command: '', args: [], deps: [], url: '' }
  envRows.value = []
  headerRows.value = []
  runtimeResult.value = null
}

const suggestCommands = (query: string, cb: (items: { value: string }[]) => void) => {
  const items = COMMON_COMMANDS
    .filter((c) => c.includes(query))
    .map((c) => ({ value: c }))
  cb(items)
}

const doCheckRuntime = async () => {
  if (!form.value.command.trim()) {
    ElMessage.warning('请先填写命令')
    return
  }
  runtimeChecking.value = true
  try {
    runtimeResult.value = await mcpStore.checkRuntime(buildConfig())
  } finally {
    runtimeChecking.value = false
  }
}

const doInstallUv = async () => {
  installingTool.value = true
  try {
    const ok = await mcpStore.installRuntimeTool('uv')
    if (ok) {
      // 装完复检
      await doCheckRuntime()
    }
  } finally {
    installingTool.value = false
  }
}

const buildConfig = (): MCPServerConfig => {
  const cfg: MCPServerConfig = {
    type: form.value.type,
    description: form.value.description || undefined
  }
  if (form.value.type === 'stdio') {
    cfg.command = form.value.command.trim()
    cfg.args = form.value.args.map((a) => a.trim()).filter(Boolean)
    const env: Record<string, string> = {}
    envRows.value.forEach(({ key, value }) => {
      if (key.trim()) env[key.trim()] = value
    })
    if (Object.keys(env).length) cfg.env = env
    const deps = form.value.deps.map((d) => d.trim()).filter(Boolean)
    if (deps.length) cfg.deps = deps
  } else {
    cfg.url = form.value.url.trim()
    const headers: Record<string, string> = {}
    headerRows.value.forEach(({ key, value }) => {
      if (key.trim()) headers[key.trim()] = value
    })
    if (Object.keys(headers).length) cfg.headers = headers
  }
  return cfg
}

const validate = (): boolean => {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写服务器名称')
    return false
  }
  if (form.value.type === 'stdio' && !form.value.command.trim()) {
    ElMessage.warning('stdio 类型需要填写命令')
    return false
  }
  if (form.value.type !== 'stdio') {
    if (!form.value.url.trim()) {
      ElMessage.warning('请填写 URL')
      return false
    }
    if (!/^https?:\/\//.test(form.value.url.trim())) {
      ElMessage.warning('URL 必须以 http:// 或 https:// 开头')
      return false
    }
  }
  return true
}

const confirmSave = async () => {
  if (!validate()) return
  saving.value = true
  try {
    await mcpStore.batchUpdate({ mcpServers: { [form.value.name.trim()]: buildConfig() } })
    visible.value = false
    ElMessage.success(isEdit.value ? '已保存' : '添加成功')
    emit('saved')
  } catch (e: any) {
    const errorMsg = e?.response?.data?.detail || e?.message || '保存失败'
    ElMessage.error(`保存失败: ${errorMsg}`)
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.form-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-row {
  display: flex;
  gap: 16px;

  .form-item {
    flex: 1;
  }
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 13px;
  color: var(--el-text-color-regular);

  .required {
    color: var(--el-color-danger);
  }
}

.command-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.runtime-result {
  font-size: 12px;

  &.ok {
    color: #10b981;
  }

  &.fail {
    color: #ef4444;
  }
}

.kv-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  align-items: center;
}

.dialog-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #eab308;
  font-size: 12px;
  margin-top: 4px;
}
</style>
