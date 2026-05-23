<template>
  <div class="settings">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><User /></el-icon>
        个人设置
      </h1>
      <p class="page-description">
        个性化配置和偏好设置
      </p>
    </div>

    <el-row :gutter="24">
      <!-- 左侧：设置菜单 -->
      <el-col :span="6">
        <el-card class="settings-menu" shadow="never">
          <el-menu
            :default-active="activeTab"
            @select="handleMenuSelect"
            class="settings-nav"
          >
            <el-menu-item index="general">
              <el-icon><User /></el-icon>
              <span>通用设置</span>
            </el-menu-item>
            <el-menu-item index="appearance">
              <el-icon><Brush /></el-icon>
              <span>外观设置</span>
            </el-menu-item>
            <el-menu-item index="analysis">
              <el-icon><TrendCharts /></el-icon>
              <span>分析偏好</span>
            </el-menu-item>
            <el-menu-item index="notifications">
              <el-icon><Bell /></el-icon>
              <span>通知设置</span>
            </el-menu-item>
            <el-menu-item index="security">
              <el-icon><Lock /></el-icon>
              <span>安全设置</span>
            </el-menu-item>
          </el-menu>
        </el-card>
      </el-col>

      <!-- 右侧：设置内容 -->
      <el-col :span="18">
        <!-- 通用设置 -->
        <el-card v-show="activeTab === 'general'" class="settings-content" shadow="never">
          <template #header>
            <h3>通用设置</h3>
          </template>
          
          <el-form :model="generalSettings" label-width="120px">
            <el-form-item label="用户名">
              <el-input v-model="generalSettings.username" disabled />
            </el-form-item>
            
            <el-form-item label="邮箱">
              <el-input v-model="generalSettings.email" />
            </el-form-item>
            
            <el-form-item label="语言">
              <el-select v-model="generalSettings.language">
                <el-option label="简体中文" value="zh-CN" />
                <el-option label="English" value="en-US" />
              </el-select>
            </el-form-item>
            
            <el-form-item label="时区">
              <el-select v-model="generalSettings.timezone">
                <el-option label="北京时间 (UTC+8)" value="Asia/Shanghai" />
                <el-option label="纽约时间 (UTC-5)" value="America/New_York" />
                <el-option label="伦敦时间 (UTC+0)" value="Europe/London" />
              </el-select>
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" @click="saveGeneralSettings">
                保存设置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 外观设置 -->
        <el-card v-show="activeTab === 'appearance'" class="settings-content" shadow="never">
          <template #header>
            <h3>外观设置</h3>
          </template>
          
          <el-form :model="appearanceSettings" label-width="120px">
            <el-form-item label="主题模式">
              <el-radio-group v-model="appearanceSettings.theme" @change="handleThemeChange">
                <el-radio label="light">浅色主题</el-radio>
                <el-radio label="dark">深色主题</el-radio>
                <el-radio label="auto">跟随系统</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="侧边栏宽度">
              <el-slider
                v-model="appearanceSettings.sidebarWidth"
                :min="200"
                :max="400"
                :step="20"
                show-input
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="saveAppearanceSettings">
                保存设置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 分析偏好 -->
        <el-card v-show="activeTab === 'analysis'" class="settings-content" shadow="never">
          <template #header>
            <h3>分析偏好</h3>
          </template>
          
          <el-form :model="analysisSettings" label-width="120px">
            <el-form-item label="默认市场">
              <el-select v-model="analysisSettings.defaultMarket">
                <el-option label="A股" value="A股" />
                <el-option label="美股" value="美股" />
                <el-option label="港股" value="港股" />
              </el-select>
            </el-form-item>

            <el-form-item label="默认辩论轮数">
              <el-input-number
                v-model="analysisSettings.defaultDebateRounds"
                :min="1"
                :max="4"
                :step="1"
                controls-position="right"
              />
              <span style="margin-left: 12px; color: #909399; font-size: 13px;">辩论轮数上限为4，默认2</span>
            </el-form-item>

            <el-form-item label="默认分析师">
              <div v-if="loadingAnalysts" class="loading-analysts">
                <el-icon class="is-loading"><Refresh /></el-icon> 加载分析师列表...
              </div>
              <el-checkbox-group v-else v-model="analysisSettings.defaultAnalysts">
                <el-checkbox 
                  v-for="analyst in availableAnalysts" 
                  :key="analyst.id" 
                  :label="analyst.id"
                >
                  {{ analyst.name }}
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <el-form-item label="自动刷新">
              <el-switch v-model="analysisSettings.autoRefresh" />
              <span class="setting-description">自动刷新分析结果</span>
            </el-form-item>
            
            <el-form-item label="刷新间隔">
              <el-input-number
                v-model="analysisSettings.refreshInterval"
                :min="10"
                :max="300"
                :step="10"
                :disabled="!analysisSettings.autoRefresh"
              />
              <span class="setting-description">秒</span>
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" @click="saveAnalysisSettings">
                保存设置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 通知设置 -->
        <el-card v-show="activeTab === 'notifications'" class="settings-content" shadow="never">
          <template #header>
            <h3>通知设置</h3>
          </template>
          
          <el-form :model="notificationSettings" label-width="120px">
            <el-form-item label="桌面通知">
              <el-switch v-model="notificationSettings.desktop" />
              <span class="setting-description">显示桌面通知</span>
            </el-form-item>

            <el-form-item label="分析完成通知">
              <el-switch v-model="notificationSettings.analysisComplete" />
            </el-form-item>

            <el-form-item label="系统维护通知">
              <el-switch v-model="notificationSettings.systemMaintenance" />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="saveNotificationSettings">
                保存设置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 安全设置 -->
        <el-card v-show="activeTab === 'security'" class="settings-content" shadow="never">
          <template #header>
            <h3>安全设置</h3>
          </template>

          <el-form label-width="120px">
            <el-form-item label="修改密码">
              <el-button type="primary" @click="changePasswordDialogVisible = true">
                修改密码
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <!-- 修改密码对话框 -->
    <el-dialog
      v-model="changePasswordDialogVisible"
      title="修改密码"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="changePasswordFormRef"
        :model="changePasswordForm"
        :rules="changePasswordRules"
        label-width="100px"
      >
        <el-form-item label="当前密码" prop="oldPassword">
          <el-input
            v-model="changePasswordForm.oldPassword"
            type="password"
            placeholder="请输入当前密码"
            show-password
          />
        </el-form-item>

        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="changePasswordForm.newPassword"
            type="password"
            placeholder="请输入新密码（至少6位）"
            show-password
          />
        </el-form-item>

        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="changePasswordForm.confirmPassword"
            type="password"
            placeholder="请再次输入新密码"
            show-password
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="changePasswordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="changePasswordLoading" @click="handleChangePassword">
          确认修改
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { agentConfigApi } from '@/api/agentConfigs'
import { normalizeAnalystIds } from '@/constants/analysts'
import {
  User,
  Brush,
  TrendCharts,
  Bell,
  Lock,
  Refresh
} from '@element-plus/icons-vue'

const route = useRoute()
const appStore = useAppStore()
const authStore = useAuthStore()

const activeTab = ref('general')

const updateTabFromRoute = () => {
  const tab = route.query.tab as string
  if (tab && ['appearance', 'analysis', 'notifications', 'security'].includes(tab)) {
    activeTab.value = tab
  } else {
    activeTab.value = 'general'
  }
}

watch(() => route.query.tab, updateTabFromRoute, { immediate: true })

const generalSettings = ref({
  username: authStore.user?.username || 'admin',
  email: authStore.user?.email || 'admin@example.com',
  language: authStore.user?.preferences?.language || 'zh-CN',
  timezone: 'Asia/Shanghai'
})

const appearanceSettings = ref({
  theme: authStore.user?.preferences?.ui_theme || 'light',
  sidebarWidth: authStore.user?.preferences?.sidebar_width || 240
})

const analysisSettings = ref({
  defaultMarket: authStore.user?.preferences?.default_market || 'A股',
  defaultDebateRounds: authStore.user?.preferences?.default_debate_rounds ?? 2,
  defaultAnalysts: authStore.user?.preferences?.default_analysts || [],
  autoRefresh: authStore.user?.preferences?.auto_refresh ?? true,
  refreshInterval: authStore.user?.preferences?.refresh_interval || 30
})

const notificationSettings = ref({
  desktop: authStore.user?.preferences?.desktop_notifications ?? true,
  analysisComplete: authStore.user?.preferences?.analysis_complete_notification ?? true,
  systemMaintenance: authStore.user?.preferences?.system_maintenance_notification ?? true
})

interface AnalystOption {
  id: string
  name: string
  slug: string
}
const availableAnalysts = ref<AnalystOption[]>([])
const loadingAnalysts = ref(false)

const slugToShortId = (slug: string): string => {
  if (!slug) return ''
  return slug.replace('-analyst', '').replace(/-/g, '_')
}

const fetchAnalysts = async () => {
  loadingAnalysts.value = true
  try {
    const res = await agentConfigApi.getPhase(1)
    if (res.success && res.data && res.data.customModes) {
      availableAnalysts.value = res.data.customModes.map(mode => ({
        id: slugToShortId(mode.slug),
        name: mode.name,
        slug: mode.slug
      }))
    } else {
      availableAnalysts.value = []
    }
  } catch (error) {
    console.error('Failed to fetch analysts:', error)
    availableAnalysts.value = []
  } finally {
    loadingAnalysts.value = false
  }
}

watch(() => authStore.user, (newUser) => {
  if (newUser) {
    generalSettings.value.username = newUser.username || 'admin'
    generalSettings.value.email = newUser.email || 'admin@example.com'
    generalSettings.value.language = newUser.preferences?.language || 'zh-CN'

    appearanceSettings.value.theme = newUser.preferences?.ui_theme || 'light'
    appearanceSettings.value.sidebarWidth = newUser.preferences?.sidebar_width || 240

    analysisSettings.value.defaultMarket = newUser.preferences?.default_market || 'A股'
    analysisSettings.value.defaultDebateRounds = newUser.preferences?.default_debate_rounds ?? 2
    analysisSettings.value.defaultAnalysts = newUser.preferences?.default_analysts || []
    analysisSettings.value.autoRefresh = newUser.preferences?.auto_refresh ?? true
    analysisSettings.value.refreshInterval = newUser.preferences?.refresh_interval || 30

    notificationSettings.value.desktop = newUser.preferences?.desktop_notifications ?? true
    notificationSettings.value.analysisComplete = newUser.preferences?.analysis_complete_notification ?? true
    notificationSettings.value.systemMaintenance = newUser.preferences?.system_maintenance_notification ?? true
  }
}, { deep: true })

const handleMenuSelect = (index: string) => {
  activeTab.value = index
}

const handleThemeChange = (theme: string | number | boolean | undefined) => {
  appStore.setTheme(theme as any)
}

const saveGeneralSettings = async () => {
  try {
    const success = await authStore.updateUserInfo({
      email: generalSettings.value.email,
      preferences: {
        language: generalSettings.value.language
      } as any
    })
    if (success) {
      ElMessage.success('通用设置已保存')
    }
  } catch (error) {
    console.error('保存通用设置失败:', error)
    ElMessage.error('保存通用设置失败')
  }
}

const saveAppearanceSettings = async () => {
  try {
    appStore.setSidebarWidth(appearanceSettings.value.sidebarWidth)
    appStore.setTheme(appearanceSettings.value.theme as any)

    const success = await authStore.updateUserInfo({
      preferences: {
        ui_theme: appearanceSettings.value.theme,
        sidebar_width: appearanceSettings.value.sidebarWidth
      } as any
    })
    if (success) {
      ElMessage.success('外观设置已保存')
    }
  } catch (error) {
    console.error('保存外观设置失败:', error)
    ElMessage.error('保存外观设置失败')
  }
}

const saveAnalysisSettings = async () => {
  try {
    const normalizedAnalysts = normalizeAnalystIds(analysisSettings.value.defaultAnalysts)

    appStore.updatePreferences({
      defaultMarket: analysisSettings.value.defaultMarket as any,
      defaultDebateRounds: analysisSettings.value.defaultDebateRounds,
      autoRefresh: analysisSettings.value.autoRefresh,
      refreshInterval: analysisSettings.value.refreshInterval,
      defaultAnalysts: normalizedAnalysts
    } as any)

    const success = await authStore.updateUserInfo({
      preferences: {
        default_market: analysisSettings.value.defaultMarket,
        default_debate_rounds: analysisSettings.value.defaultDebateRounds,
        default_analysts: normalizedAnalysts,
        auto_refresh: analysisSettings.value.autoRefresh,
        refresh_interval: analysisSettings.value.refreshInterval
      } as any
    })
    if (success) {
      ElMessage.success('分析偏好已保存')
    }
  } catch (error) {
    console.error('保存分析偏好失败:', error)
    ElMessage.error('保存分析偏好失败')
  }
}

const saveNotificationSettings = async () => {
  try {
    const success = await authStore.updateUserInfo({
      preferences: {
        desktop_notifications: notificationSettings.value.desktop,
        analysis_complete_notification: notificationSettings.value.analysisComplete,
        system_maintenance_notification: notificationSettings.value.systemMaintenance,
        notifications_enabled: notificationSettings.value.desktop || notificationSettings.value.analysisComplete || notificationSettings.value.systemMaintenance
      } as any
    })
    if (success) {
      ElMessage.success('通知设置已保存')
    }
  } catch (error) {
    console.error('保存通知设置失败:', error)
    ElMessage.error('保存通知设置失败')
  }
}

const changePasswordDialogVisible = ref(false)
const changePasswordLoading = ref(false)
const changePasswordFormRef = ref()
const changePasswordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const validateConfirmPassword = (_rule: any, value: any, callback: any) => {
  if (value === '') {
    callback(new Error('请再次输入新密码'))
  } else if (value !== changePasswordForm.value.newPassword) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const changePasswordRules = {
  oldPassword: [
    { required: true, message: '请输入当前密码', trigger: 'blur' }
  ],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少为6位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

const handleChangePassword = async () => {
  if (!changePasswordFormRef.value) return

  await changePasswordFormRef.value.validate(async (valid: boolean) => {
    if (valid) {
      changePasswordLoading.value = true
      try {
        const success = await authStore.changePassword(
          changePasswordForm.value.oldPassword,
          changePasswordForm.value.newPassword
        )

        if (success) {
          ElMessage.success('密码修改成功，请重新登录')
          changePasswordDialogVisible.value = false
          changePasswordForm.value = {
            oldPassword: '',
            newPassword: '',
            confirmPassword: ''
          }
          setTimeout(() => {
            authStore.logout()
          }, 1500)
        }
      } catch (error: any) {
        ElMessage.error(error.message || '密码修改失败')
      } finally {
        changePasswordLoading.value = false
      }
    }
  })
}

onMounted(async () => {
  await fetchAnalysts()
  
  appearanceSettings.value.theme = appStore.theme
  appearanceSettings.value.sidebarWidth = appStore.sidebarWidth
  
  analysisSettings.value.defaultMarket = appStore.preferences.defaultMarket
  analysisSettings.value.defaultDebateRounds = appStore.preferences.defaultDebateRounds ?? 2
  analysisSettings.value.autoRefresh = appStore.preferences.autoRefresh
  analysisSettings.value.refreshInterval = appStore.preferences.refreshInterval
})
</script>

<style lang="scss" scoped>
.settings {
  .page-header {
    margin-bottom: 24px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0;
    }
  }

  .settings-menu {
    .settings-nav {
      border: none;
    }
  }

  .settings-content {
    min-height: 500px;

    .setting-description {
      margin-left: 8px;
      font-size: 12px;
      color: var(--el-text-color-placeholder);
    }
  }
}
</style>
