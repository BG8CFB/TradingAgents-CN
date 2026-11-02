<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>数据源接入</h3>
          <div class="header-actions">
            <el-button @click="showMarketCategoryManagement">
              <el-icon><Setting /></el-icon>
              管理分类
            </el-button>
            <el-button type="primary" @click="showAddDataSourceDialog">
              <el-icon><Plus /></el-icon>
              添加数据源
            </el-button>
          </div>
        </div>
      </template>

      <div v-loading="dataSourceLoading" class="datasource-content">
        <!-- 数据源分组展示 -->
        <div v-if="dataSourceGroups.length > 0" class="datasource-groups">
          <SortableDataSourceList
            v-for="group in dataSourceGroups"
            :key="group.categoryId"
            :category-id="group.categoryId"
            :category-display-name="group.categoryDisplayName"
            :data-sources="group.dataSources"
            @update-order="handleUpdateDataSourceOrder"
            @edit-datasource="editDataSourceConfig"
            @manage-grouping="showDataSourceGroupingDialog"
            @manage-category="showMarketCategoryManagement"
            @add-datasource="showAddDataSourceDialog"
            @delete-datasource="deleteDataSourceConfig"
          />
        </div>

        <!-- 未分组的数据源 -->
        <div v-if="ungroupedDataSources.length > 0" class="ungrouped-section">
          <el-card shadow="never">
            <template #header>
              <div class="section-header">
                <h4>未分组数据源</h4>
                <el-tag type="warning" size="small">{{ ungroupedDataSources.length }} 个</el-tag>
              </div>
            </template>

            <div class="ungrouped-list">
              <div
                v-for="dataSource in ungroupedDataSources"
                :key="dataSource.name"
                class="ungrouped-item"
              >
                <div class="item-info">
                  <span class="item-name">{{ dataSource.display_name || dataSource.name }}</span>
                  <el-tag :type="dataSource.enabled ? 'success' : 'danger'" size="small">
                    {{ dataSource.enabled ? '启用' : '禁用' }}
                  </el-tag>
                  <span class="item-type">{{ dataSource.type }}</span>
                </div>
                <div class="item-actions">
                  <el-button size="small" @click="editDataSourceConfig(dataSource)">
                    编辑
                  </el-button>
                  <el-button size="small" @click="showDataSourceGroupingDialog(dataSource.name)">
                    分组
                  </el-button>
                  <el-button size="small" type="primary" @click="testDataSource(dataSource)">
                    测试
                  </el-button>
                  <el-button size="small" type="danger" @click="deleteDataSourceConfig(dataSource)">
                    删除
                  </el-button>
                </div>
              </div>
            </div>
          </el-card>
        </div>

        <!-- 空状态 -->
        <div v-if="dataSourceConfigs.length === 0" class="empty-state">
          <el-empty description="暂无数据源配置">
            <el-button type="primary" @click="showAddDataSourceDialog">
              添加第一个数据源
            </el-button>
          </el-empty>
        </div>
      </div>
    </el-card>

    <!-- 数据源配置对话框 -->
    <DataSourceConfigDialog
      v-model:visible="dataSourceDialogVisible"
      :config="currentDataSourceConfig"
      @success="handleDataSourceConfigSuccess"
    />

    <!-- 市场分类管理对话框 -->
    <el-dialog
      v-model="marketCategoryManagementVisible"
      title="市场分类管理"
      width="80%"
      :close-on-click-modal="false"
    >
      <MarketCategoryManagement @success="handleMarketCategorySuccess" />
    </el-dialog>

    <!-- 数据源分组对话框 -->
    <DataSourceGroupingDialog
      v-model:visible="dataSourceGroupingDialogVisible"
      :data-source-name="currentDataSourceName"
      @success="handleDataSourceGroupingSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting, Plus } from '@element-plus/icons-vue'
import {
  configApi,
  type DataSourceConfig,
  type MarketCategory,
  type DataSourceGrouping
} from '@/api/config'
import DataSourceConfigDialog from '@/views/Settings/components/DataSourceConfigDialog.vue'
import MarketCategoryManagement from '@/views/Settings/components/MarketCategoryManagement.vue'
import DataSourceGroupingDialog from '@/views/Settings/components/DataSourceGroupingDialog.vue'
import SortableDataSourceList from '@/views/Settings/components/SortableDataSourceList.vue'

// 响应式数据
const dataSourceConfigs = ref<DataSourceConfig[]>([])
const defaultDataSource = ref<string>('')

// 数据源分组相关
const marketCategories = ref<MarketCategory[]>([])
const dataSourceGroupings = ref<DataSourceGrouping[]>([])
const dataSourceGroups = ref<any[]>([])
const ungroupedDataSources = ref<DataSourceConfig[]>([])
const dataSourceLoading = ref(false)

// 数据源相关对话框
const dataSourceDialogVisible = ref(false)
const currentDataSourceConfig = ref<DataSourceConfig | null>(null)
const marketCategoryManagementVisible = ref(false)
const dataSourceGroupingDialogVisible = ref(false)
const currentDataSourceName = ref<string>('')

const loadDataSourceConfigs = async () => {
  dataSourceLoading.value = true
  try {
    const configs = await configApi.getDataSourceConfigs()
    dataSourceConfigs.value = Array.isArray(configs) ? configs : configs.data

    // 获取默认数据源
    const systemConfig = await configApi.getSystemConfig()
    const sysData = systemConfig.data || systemConfig
    defaultDataSource.value = sysData.default_data_source || ''

    // 加载分组相关数据
    await loadMarketCategories()
    await loadDataSourceGroupings()
    buildDataSourceGroups()
  } catch (error) {
    ElMessage.error('加载数据源配置失败')
  } finally {
    dataSourceLoading.value = false
  }
}

// 加载市场分类
const loadMarketCategories = async () => {
  try {
    const resp = await configApi.getMarketCategories()
    marketCategories.value = Array.isArray(resp) ? resp : resp.data
  } catch (error) {
    console.error('加载市场分类失败:', error)
  }
}

// 加载数据源分组关系
const loadDataSourceGroupings = async () => {
  try {
    const resp = await configApi.getDataSourceGroupings()
    dataSourceGroupings.value = Array.isArray(resp) ? resp : resp.data
  } catch (error) {
    console.error('加载数据源分组关系失败:', error)
  }
}

// 构建数据源分组
const buildDataSourceGroups = () => {
  const groups: any[] = []
  const ungrouped: DataSourceConfig[] = []

  // 按分类分组
  marketCategories.value.forEach(category => {
    const categoryGroupings = dataSourceGroupings.value.filter(
      g => g.market_category_id === category.id
    )

    if (categoryGroupings.length > 0) {
      const dataSources = categoryGroupings
        .map(grouping => {
          const dataSource = dataSourceConfigs.value.find(
            ds => ds.name === grouping.data_source_name
          )
          if (dataSource) {
            return {
              ...dataSource,
              priority: grouping.priority,
              enabled: grouping.enabled
            }
          }
          return null
        })
        .filter((ds): ds is DataSourceConfig & { priority: number } => ds !== null)
        .sort((a, b) => b.priority - a.priority) // 按优先级降序排列

      groups.push({
        categoryId: category.id,
        categoryDisplayName: category.display_name,
        dataSources
      })
    }
  })

  // 找出未分组的数据源
  const groupedDataSourceNames = new Set(
    dataSourceGroupings.value.map(g => g.data_source_name)
  )

  dataSourceConfigs.value.forEach(dataSource => {
    if (!groupedDataSourceNames.has(dataSource.name)) {
      ungrouped.push(dataSource)
    }
  })

  dataSourceGroups.value = groups
  ungroupedDataSources.value = ungrouped
}

const showAddDataSourceDialog = () => {
  currentDataSourceConfig.value = null
  dataSourceDialogVisible.value = true
}

const editDataSourceConfig = (config: DataSourceConfig) => {
  currentDataSourceConfig.value = config
  dataSourceDialogVisible.value = true
}

// 显示市场分类管理
const showMarketCategoryManagement = () => {
  marketCategoryManagementVisible.value = true
}

// 显示数据源分组对话框
const showDataSourceGroupingDialog = (dataSourceName: string) => {
  currentDataSourceName.value = dataSourceName
  dataSourceGroupingDialogVisible.value = true
}

// 处理数据源排序更新
const handleUpdateDataSourceOrder = async (categoryId: string, orderedItems: Array<{name: string, priority: number}>) => {
  try {
    await configApi.updateCategoryDataSourceOrder(categoryId, orderedItems)
    ElMessage.success('排序更新成功')
    // 重新加载数据
    await loadDataSourceGroupings()
    buildDataSourceGroups()
  } catch (error) {
    console.error('更新排序失败:', error)
    ElMessage.error('更新排序失败')
  }
}

// 数据源配置成功回调
const handleDataSourceConfigSuccess = () => {
  loadDataSourceConfigs()
}

// 市场分类管理成功回调
const handleMarketCategorySuccess = () => {
  loadMarketCategories()
  buildDataSourceGroups()
}

// 数据源分组成功回调
const handleDataSourceGroupingSuccess = () => {
  loadDataSourceGroupings()
  buildDataSourceGroups()
}

const testDataSource = async (config: DataSourceConfig) => {
  try {
    const result = await configApi.testConfig({
      config_type: 'datasource',
      config_data: config
    })

    if (result.success) {
      ElMessage.success('数据源连接测试成功')
    } else {
      ElMessage.error(`数据源连接测试失败: ${result.message}`)
    }
  } catch (error) {
    ElMessage.error('数据源连接测试失败')
  }
}

// 删除数据源配置
const deleteDataSourceConfig = async (config: DataSourceConfig) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除数据源 "${config.display_name || config.name}" 吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )

    await configApi.deleteDataSourceConfig(config.name)
    ElMessage.success('数据源删除成功')
    await loadDataSourceConfigs()
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('删除数据源失败:', error)
      ElMessage.error(error.message || '删除数据源失败')
    }
  }
}

// 供父组件按 tab 懒加载
defineExpose({ reload: loadDataSourceConfigs })
</script>

<style lang="scss" scoped>
.config-content {
  min-height: 500px;

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    h3 {
      margin: 0;
    }

    .header-actions {
      display: flex;
      gap: 8px;
    }
  }

  .datasource-content {
    .datasource-groups {
      margin-bottom: 24px;
    }

    .ungrouped-section {
      margin-bottom: 24px;

      .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;

        h4 {
          margin: 0;
          color: var(--el-text-color-primary);
          font-size: 14px;
        }
      }

      .ungrouped-list {
        .ungrouped-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 0;
          border-bottom: 1px solid #f0f0f0;

          &:last-child {
            border-bottom: none;
          }

          .item-info {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 12px;

            .item-name {
              font-weight: 500;
              color: var(--el-text-color-primary);
            }

            .item-type {
              color: var(--el-text-color-placeholder);
              font-size: 12px;
            }
          }

          .item-actions {
            display: flex;
            gap: 8px;
          }
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 60px 20px;
    }
  }
}
</style>
