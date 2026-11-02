<template>
  <div class="ai-chat-page">
    <el-container class="chat-container">
      <el-aside width="240px" class="chat-aside">
        <SessionSidebar
          :sessions="store.sessions"
          :current-session-id="store.currentSessionId"
          :creating="creating"
          @create="handleCreate"
          @select="handleSelect"
          @remove="handleRemove"
        />
      </el-aside>

      <el-container class="chat-main">
        <header class="chat-header">
          <div class="chat-header-title">
            <!-- 移动端：会话列表入口 -->
            <el-button v-if="isMobile" link class="session-toggle" @click="sessionDrawer = true" aria-label="会话列表">
              <el-icon :size="18"><Menu /></el-icon>
            </el-button>
            <el-icon><ChatDotRound /></el-icon>
            <span>AI 选股助手</span>
          </div>
          <div class="chat-header-meta">
            <el-tag size="small" :type="store.wsConnected ? 'success' : 'info'" effect="plain">
              {{ store.wsConnected ? '已连接' : '连接中…' }}
            </el-tag>
            <el-tag v-if="store.quotaRemaining !== null" size="small" type="info" effect="plain">
              今日剩余 {{ store.quotaRemaining }} 轮
            </el-tag>
          </div>
        </header>

        <MessageList
          :messages="store.messages"
          :streaming-text="store.streamingText"
          :streaming-thinking="store.streamingThinking"
          :running="store.running"
        />

        <InputBox
          :running="store.running"
          :ws-connected="store.wsConnected"
          :quota-remaining="store.quotaRemaining"
          :disabled="!store.chatEnabled"
          @send="handleSend"
          @stop="store.stop()"
        />
      </el-container>
    </el-container>

    <!-- 移动端会话抽屉 -->
    <el-drawer
      v-if="isMobile"
      v-model="sessionDrawer"
      direction="ltr"
      size="80vw"
      :with-header="false"
    >
      <SessionSidebar
        :sessions="store.sessions"
        :current-session-id="store.currentSessionId"
        :creating="creating"
        @create="creating = false; sessionDrawer = false"
        @select="sessionDrawer = false"
        @remove="() => {}"
      />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onActivated, ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Menu } from '@element-plus/icons-vue'
import { useWindowSize } from '@vueuse/core'
import { useChatProcessStore } from '@/stores/chatProcess'
import SessionSidebar from './components/SessionSidebar.vue'
import MessageList from './components/MessageList.vue'
import InputBox from './components/InputBox.vue'

defineOptions({ name: 'AiChat' })

const store = useChatProcessStore()
const creating = ref(false)
const sessionDrawer = ref(false)
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

let lastLoadedAt = 0

onMounted(async () => {
  lastLoadedAt = Date.now()
  try {
    await store.loadSessions()
    if (store.sessions.length) {
      await store.loadSession(store.sessions[0].session_id)
    } else {
      await handleCreate()
    }
    await store.refreshQuota()
  } catch {
    ElMessage.error('初始化会话列表失败，请刷新重试')
  }
})

// keep-alive 复活新鲜度：距上次加载超过 60s 只刷新会话列表与配额展示，
// 不动当前会话消息流（避免打断正在进行的对话）
onActivated(() => {
  if (Date.now() - lastLoadedAt <= 60 * 1000) return
  lastLoadedAt = Date.now()
  void store.loadSessions().catch(() => {})
  void store.refreshQuota().catch(() => {})
})

// 轮次结束（审计落库）后刷新配额展示
watch(
  () => store.running,
  (running, wasRunning) => {
    if (wasRunning && !running) void store.refreshQuota()
  }
)

async function handleCreate() {
  creating.value = true
  try {
    await store.createSession()
  } catch {
    ElMessage.error('创建会话失败')
  } finally {
    creating.value = false
  }
}

async function handleSelect(sessionId: string) {
  try {
    await store.loadSession(sessionId)
  } catch {
    ElMessage.error('加载会话失败')
  }
}

async function handleRemove(sessionId: string) {
  try {
    await store.deleteSession(sessionId)
    // 删除当前会话后切到最近会话，没有则新建
    if (!store.currentSessionId) {
      if (store.sessions.length) await store.loadSession(store.sessions[0].session_id)
      else await handleCreate()
    }
    ElMessage.success('会话已删除')
  } catch {
    ElMessage.error('删除会话失败')
  }
}

async function handleSend(content: string) {
  const error = await store.sendMessage(content)
  if (error) ElMessage.warning(error)
}
</script>

<style scoped>
.ai-chat-page {
  height: 100%;
  padding: 0;
}

.chat-container {
  height: 100%;
  background: var(--el-bg-color);
}

.chat-aside {
  height: 100%;
  overflow: hidden;
}

.chat-main {
  flex-direction: column;
  height: 100%;
  min-width: 0;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.chat-header-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 600;

  .session-toggle {
    padding: 8px;
    margin-right: 2px;
  }
}

.chat-header-meta {
  display: flex;
  gap: 8px;
}
</style>
