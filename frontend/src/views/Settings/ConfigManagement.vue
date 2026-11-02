<template>
  <div class="config-management">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">
          <el-icon><Setting /></el-icon>
          配置管理
        </h1>
        <p class="page-description">
          管理系统配置、大模型、数据源等设置
        </p>
      </div>
      <div class="header-right">
        <el-button type="success" @click="handleReloadConfig" :loading="reloadLoading">
          <el-icon><Refresh /></el-icon>
          重载配置
        </el-button>
      </div>
    </div>

    <el-row :gutter="24">
      <!-- 左侧：配置菜单 -->
      <el-col :span="4">
        <el-card class="config-menu" shadow="never">
          <el-menu
            :default-active="activeTab"
            @select="handleMenuSelect"
            class="config-nav"
          >
            <el-menu-item index="providers">
              <el-icon><OfficeBuilding /></el-icon>
              <span>厂家管理</span>
            </el-menu-item>
            <el-menu-item index="llm">
              <el-icon><Cpu /></el-icon>
              <span>大模型配置</span>
            </el-menu-item>
            <el-menu-item index="datasource">
              <el-icon><DataBoard /></el-icon>
              <span>数据源接入</span>
            </el-menu-item>
            <el-menu-item index="database">
              <el-icon><Coin /></el-icon>
              <span>数据库配置</span>
            </el-menu-item>
            <el-menu-item index="system">
              <el-icon><Tools /></el-icon>
              <span>系统设置</span>
            </el-menu-item>
            <el-menu-item index="api-keys">
              <el-icon><Key /></el-icon>
              <span>API密钥状态</span>
            </el-menu-item>
            <el-menu-item index="import-export">
              <el-icon><Download /></el-icon>
              <span>导入导出</span>
            </el-menu-item>
          </el-menu>
        </el-card>
      </el-col>

      <!-- 右侧：配置内容（各 tab 子组件，v-show 保持原有常驻挂载语义） -->
      <el-col :span="20">
        <ProvidersTab
          ref="providersTabRef"
          v-show="activeTab === 'providers'"
          @add="showAddProviderDialog"
          @edit="editProvider"
        />
        <LlmConfigTab
          ref="llmTabRef"
          v-show="activeTab === 'llm'"
        />
        <DataSourceTab
          ref="dataSourceTabRef"
          v-show="activeTab === 'datasource'"
        />
        <DatabaseTab
          ref="databaseTabRef"
          v-show="activeTab === 'database'"
        />
        <SystemConfigTab
          ref="systemTabRef"
          v-show="activeTab === 'system'"
        />
        <ApiKeysTab
          ref="apiKeysTabRef"
          v-show="activeTab === 'api-keys'"
          @edit-provider="editProvider"
          @navigate="handleNavigate"
        />
        <ImportExportTab v-show="activeTab === 'import-export'" />
      </el-col>
    </el-row>

    <!-- 厂家管理对话框（「厂家管理」与「API密钥状态」两个 tab 共用） -->
    <ProviderDialog
      v-model:visible="providerDialogVisible"
      :provider="currentProvider"
      @success="handleProviderSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Setting,
  Cpu,
  DataBoard,
  Coin,
  Tools,
  Download,
  Refresh,
  Key,
  OfficeBuilding,
} from '@element-plus/icons-vue'

import { configApi, type LLMProvider } from '@/api/config'
import ProviderDialog from './components/ProviderDialog.vue'
import ProvidersTab from '@/components/Settings/ProvidersTab.vue'
import LlmConfigTab from '@/components/Settings/LlmConfigTab.vue'
import DataSourceTab from '@/components/Settings/DataSourceTab.vue'
import DatabaseTab from '@/components/Settings/DatabaseTab.vue'
import SystemConfigTab from '@/components/Settings/SystemConfigTab.vue'
import ApiKeysTab from '@/components/Settings/ApiKeysTab.vue'
import ImportExportTab from '@/components/Settings/ImportExportTab.vue'

// 响应式数据
const activeTab = ref('providers')
const reloadLoading = ref(false)

// 厂家对话框（providers / api-keys 两个 tab 共用）
const providerDialogVisible = ref(false)
const currentProvider = ref<Partial<LLMProvider>>({})

// 各 tab 子组件引用：按 tab 懒加载数据（等价拆分前的 loadTabData 分发）
const providersTabRef = ref<InstanceType<typeof ProvidersTab> | null>(null)
const llmTabRef = ref<InstanceType<typeof LlmConfigTab> | null>(null)
const dataSourceTabRef = ref<InstanceType<typeof DataSourceTab> | null>(null)
const databaseTabRef = ref<InstanceType<typeof DatabaseTab> | null>(null)
const systemTabRef = ref<InstanceType<typeof SystemConfigTab> | null>(null)
const apiKeysTabRef = ref<InstanceType<typeof ApiKeysTab> | null>(null)

// 方法
const handleMenuSelect = (index: string) => {
  activeTab.value = index
  reloadTab(index)
}

// 按 tab 懒加载（import-export 无数据需加载）
const reloadTab = (tab: string) => {
  switch (tab) {
    case 'providers':
      providersTabRef.value?.reload()
      break
    case 'llm':
      llmTabRef.value?.reload()
      break
    case 'datasource':
      dataSourceTabRef.value?.reload()
      break
    case 'database':
      databaseTabRef.value?.reload()
      break
    case 'system':
      systemTabRef.value?.reload()
      break
    case 'api-keys':
      apiKeysTabRef.value?.reload()
      break
  }
}

// 子组件内部跳转 tab（原实现仅切换 activeTab，不触发数据加载）
const handleNavigate = (tab: string) => {
  activeTab.value = tab
}

// 显示添加厂家对话框
const showAddProviderDialog = () => {
  currentProvider.value = {}
  providerDialogVisible.value = true
}

// 编辑厂家
const editProvider = (provider: LLMProvider) => {
  currentProvider.value = { ...provider }
  providerDialogVisible.value = true
}

// 厂家操作成功回调：刷新两个持有厂家列表的 tab
const handleProviderSuccess = () => {
  providersTabRef.value?.reload()
  apiKeysTabRef.value?.reload()
}

// 配置重载
const handleReloadConfig = async () => {
  try {
    reloadLoading.value = true
    const response = await configApi.reloadConfig()

    if (response.success) {
      ElMessage.success({
        message: '配置重载成功！新配置已生效',
        duration: 3000
      })
    } else {
      ElMessage.warning({
        message: response.message || '配置重载失败',
        duration: 3000
      })
    }
  } catch (error: any) {
    console.error('配置重载失败:', error)
    ElMessage.error({
      message: error.response?.data?.detail || '配置重载失败',
      duration: 3000
    })
  } finally {
    reloadLoading.value = false
  }
}

// 生命周期
onMounted(() => {
  reloadTab(activeTab.value)
})
</script>

<style lang="scss" scoped>
.config-management {
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;

    .header-left {
      flex: 1;

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
        margin: 0;
        color: var(--el-text-color-secondary);
        font-size: 14px;
      }
    }

    .header-right {
      display: flex;
      gap: 12px;
    }
  }

  .config-menu {
    .config-nav {
      border: none;
    }
  }
}
</style>
