<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <h3>导入导出</h3>
      </template>

      <div class="import-export-content">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
        >
          <template #title>
            导出范围：系统配置、AI厂家、模型目录、市场分类、数据源分组、智能体(Agent)配置
          </template>
          <template #default>
            敏感信息（API Key、密码、Token）导出时自动脱敏，导入后需重新配置
          </template>
        </el-alert>

        <el-row :gutter="24">
          <el-col :span="12">
            <h4>导出配置</h4>
            <p>将当前全部配置导出为 JSON 文件，可用于备份或迁移到其他实例</p>
            <el-button type="primary" @click="exportConfig" :loading="exportLoading">
              <el-icon><Download /></el-icon>
              导出配置
            </el-button>
          </el-col>

          <el-col :span="12">
            <h4>导入配置</h4>
            <p>从 JSON 文件导入配置（将覆盖现有配置，敏感信息需重新填写）</p>
            <el-upload
              :before-upload="handleImportConfig"
              :show-file-list="false"
              accept=".json"
            >
              <el-button type="success" :loading="importLoading">
                <el-icon><Upload /></el-icon>
                导入配置
              </el-button>
            </el-upload>
          </el-col>
        </el-row>

        <el-divider />

        <div class="legacy-migration">
          <h4>传统配置迁移</h4>
          <p>将内置智能体种子同步到数据库（幂等：内置项按哈希覆盖升级，用户修改项不动）</p>
          <el-button type="warning" @click="migrateLegacyConfig" :loading="migrateLoading">
            <el-icon><Refresh /></el-icon>
            迁移传统配置
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Upload, Refresh } from '@element-plus/icons-vue'
import { configApi } from '@/api/config'

// 响应式数据
const exportLoading = ref(false)
const importLoading = ref(false)
const migrateLoading = ref(false)

const exportConfig = async () => {
  exportLoading.value = true
  try {
    const result = await configApi.exportConfig()

    // 创建下载链接
    const blob = new Blob([JSON.stringify(result.data, null, 2)], {
      type: 'application/json'
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `tradingagents-config-${new Date().toISOString().split('T')[0]}.json`
    link.click()
    URL.revokeObjectURL(url)

    // 统计导出项
    const data = (result.data as Record<string, any>) || {}
    const items: string[] = []
    if (data.system_configs) items.push('系统配置')
    if (data.llm_providers?.length) items.push(`厂家(${data.llm_providers.length})`)
    if (data.model_catalog?.length) items.push(`模型目录(${data.model_catalog.length})`)
    if (data.market_categories?.length) items.push('市场分类')
    if (data.datasource_groupings?.length) items.push('数据源分组')
    if (data.agent_configs && Object.keys(data.agent_configs).length) items.push('智能体配置')
    const summary = items.length ? items.join('、') : '基本配置'
    ElMessage.success(`配置导出成功（含 ${summary}）`)
  } catch (error) {
    ElMessage.error('配置导出失败')
  } finally {
    exportLoading.value = false
  }
}

const handleImportConfig = async (file: File) => {
  importLoading.value = true
  try {
    const text = await file.text()
    const configData = JSON.parse(text)

    // 生成覆盖范围提示
    const scopeParts: string[] = ['系统配置（LLM/数据源/数据库/系统设置）']
    if (configData.llm_providers?.length) scopeParts.push('厂家配置')
    if (configData.model_catalog?.length) scopeParts.push('模型目录')
    if (configData.market_categories?.length) scopeParts.push('市场分类')
    if (configData.datasource_groupings?.length) scopeParts.push('数据源分组')
    if (configData.agent_configs && Object.keys(configData.agent_configs).length) scopeParts.push('智能体配置')
    const scopeText = scopeParts.join('、')

    await ElMessageBox.confirm(
      `导入将覆盖以下配置：${scopeText}。敏感信息（API Key、密码）不会被导入，需重新配置。确定继续？`,
      '确认导入',
      { type: 'warning', confirmButtonText: '确定导入', cancelButtonText: '取消' }
    )

    await configApi.importConfig(configData)

    // 导入成功后触发配置重载
    try {
      await configApi.reloadConfig()
    } catch (_) { /* 重载失败不影响导入结果 */ }

    ElMessage.success('配置导入成功，已自动刷新')
    // 其余 tab 的数据在下次切换时按懒加载语义重新拉取
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('配置导入失败')
    }
  } finally {
    importLoading.value = false
  }

  return false // 阻止自动上传
}

const migrateLegacyConfig = async () => {
  migrateLoading.value = true
  try {
    await ElMessageBox.confirm(
      '将把内置智能体种子同步到数据库（幂等，不影响用户自定义配置）。确定继续？',
      '确认迁移',
      { type: 'warning' }
    )

    await configApi.migrateLegacyConfig()

    // 迁移后触发配置重载
    try {
      await configApi.reloadConfig()
    } catch (_) { /* ignore */ }

    ElMessage.success('传统配置迁移成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('传统配置迁移失败')
    }
  } finally {
    migrateLoading.value = false
  }
}
</script>

<style lang="scss" scoped>
.config-content {
  min-height: 500px;

  .import-export-content {
    h4 {
      margin: 0 0 8px 0;
      color: var(--el-text-color-primary);
    }

    p {
      margin: 0 0 16px 0;
      color: var(--el-text-color-regular);
      font-size: 14px;
    }

    .legacy-migration {
      margin-top: 24px;
    }
  }
}
</style>
