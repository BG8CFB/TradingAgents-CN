<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>数据库配置</h3>
          <el-text type="info" size="small">系统核心数据库配置，仅支持编辑和测试</el-text>
        </div>
      </template>

      <div v-loading="databaseLoading">
        <el-table :data="databaseConfigs" style="width: 100%">
          <el-table-column prop="name" label="名称" width="150" />
          <el-table-column prop="type" label="类型" width="120" />
          <el-table-column prop="host" label="主机" width="150" />
          <el-table-column prop="port" label="端口" width="100" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'danger'">
                {{ row.enabled ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button size="small" @click="editDatabaseConfig(row)">编辑</el-button>
              <el-button size="small" type="primary" @click="testDatabase(row)">
                测试连接
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 数据库配置对话框 -->
    <el-dialog
      v-model="databaseDialogVisible"
      title="编辑数据库配置"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="提示"
        type="info"
        :closable="false"
        style="margin-bottom: 20px"
      >
        数据库配置是系统核心配置，配置名称和类型不可修改。如果配置中未填写用户名密码，系统将使用环境变量（.env文件）中的配置。
      </el-alert>

      <el-form :model="currentDatabaseConfig" label-width="120px">
        <el-form-item label="配置名称" required>
          <el-input
            v-model="currentDatabaseConfig.name"
            placeholder="请输入配置名称"
            disabled
          />
        </el-form-item>

        <el-form-item label="数据库类型" required>
          <el-select v-model="currentDatabaseConfig.type" placeholder="请选择数据库类型" disabled>
            <el-option label="MongoDB" value="mongodb" />
            <el-option label="Redis" value="redis" />
            <el-option label="MySQL" value="mysql" />
            <el-option label="PostgreSQL" value="postgresql" />
            <el-option label="SQLite" value="sqlite" />
          </el-select>
        </el-form-item>

        <el-form-item label="主机地址" required>
          <el-input v-model="currentDatabaseConfig.host" placeholder="例如: localhost" />
        </el-form-item>

        <el-form-item label="端口号" required>
          <el-input-number
            v-model="currentDatabaseConfig.port"
            :min="1"
            :max="65535"
            placeholder="例如: 27017"
          />
        </el-form-item>

        <el-form-item label="用户名">
          <el-input v-model="currentDatabaseConfig.username" placeholder="请输入用户名" />
        </el-form-item>

        <el-form-item label="密码">
          <el-input
            v-model="currentDatabaseConfig.password"
            type="password"
            placeholder="请输入密码"
            show-password
          />
        </el-form-item>

        <el-form-item label="数据库名">
          <el-input v-model="currentDatabaseConfig.database" placeholder="请输入数据库名" />
        </el-form-item>

        <el-form-item label="连接池大小">
          <el-input-number v-model="currentDatabaseConfig.pool_size" :min="1" :max="100" />
        </el-form-item>

        <el-form-item label="最大溢出连接">
          <el-input-number v-model="currentDatabaseConfig.max_overflow" :min="0" :max="200" />
        </el-form-item>

        <el-form-item label="启用状态">
          <el-switch v-model="currentDatabaseConfig.enabled" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="currentDatabaseConfig.description"
            type="textarea"
            :rows="3"
            placeholder="请输入配置描述"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="databaseDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDatabaseConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { configApi, type DatabaseConfig } from '@/api/config'

// 响应式数据
const databaseConfigs = ref<DatabaseConfig[]>([])
const databaseLoading = ref(false)

// 数据库配置对话框
const databaseDialogVisible = ref(false)
const databaseDialogMode = ref<'add' | 'edit'>('add')
const currentDatabaseConfig = ref<Partial<DatabaseConfig>>({
  name: '',
  type: 'mongodb',
  host: 'localhost',
  port: 27017,
  username: '',
  password: '',
  database: '',
  connection_params: {},
  pool_size: 10,
  max_overflow: 20,
  enabled: true,
  description: ''
})

const loadDatabaseConfigs = async () => {
  databaseLoading.value = true
  try {
    const dbResp = await configApi.getDatabaseConfigs()
    databaseConfigs.value = Array.isArray(dbResp) ? dbResp : dbResp.data
  } catch (error) {
    ElMessage.error('加载数据库配置失败')
  } finally {
    databaseLoading.value = false
  }
}

const editDatabaseConfig = (config: DatabaseConfig) => {
  databaseDialogMode.value = 'edit'
  currentDatabaseConfig.value = { ...config }
  databaseDialogVisible.value = true
}

const saveDatabaseConfig = async () => {
  try {
    const name = currentDatabaseConfig.value.name
    if (!name) {
      ElMessage.warning('配置名称不能为空')
      return
    }
    await configApi.updateDatabaseConfig(name, currentDatabaseConfig.value)
    ElMessage.success('数据库配置更新成功')
    databaseDialogVisible.value = false
    await loadDatabaseConfigs()
  } catch (error: any) {
    ElMessage.error(error.message || '保存数据库配置失败')
  }
}

const testDatabase = async (config: DatabaseConfig) => {
  try {
    const result = await configApi.testDatabaseConfig(config.name)

    if (result.success) {
      const timeStr = result.response_time ? ` (${result.response_time.toFixed(2)}s)` : ''
      ElMessage.success(`数据库连接测试成功${timeStr}`)
    } else {
      ElMessage.error(`数据库连接测试失败: ${result.message}`)
    }
  } catch (error: any) {
    console.error('❌ 数据库测试失败:', error)
    console.error('❌ 错误详情:', error.response?.data)
    ElMessage.error(error.response?.data?.detail || error.message || '数据库连接测试失败')
  }
}

// 供父组件按 tab 懒加载
defineExpose({ reload: loadDatabaseConfigs })
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
  }
}
</style>
