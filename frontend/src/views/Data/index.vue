<template>
  <div class="data-management">
    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="总览看板" name="dashboard">
        <Dashboard />
      </el-tab-pane>
      <el-tab-pane label="同步管理" name="sync">
        <SyncManagement />
      </el-tab-pane>
      <el-tab-pane label="数据源配置" name="source">
        <SourceConfig />
      </el-tab-pane>
      <el-tab-pane label="股票数据" name="viewer">
        <StockDataViewer />
      </el-tab-pane>
      <el-tab-pane label="数据质量" name="quality">
        <DataQuality />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Dashboard from './Dashboard.vue'
import SyncManagement from './SyncManagement.vue'
import SourceConfig from './SourceConfig.vue'
import StockDataViewer from './StockDataViewer.vue'
import DataQuality from './DataQuality.vue'

const activeTab = ref('dashboard')
</script>

<style scoped>
.data-management {
  padding: 20px;
}
</style>
