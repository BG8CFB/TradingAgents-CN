<template>
  <div class="features-section">
    <div class="section-header">
      <h2 class="section-title">核心功能</h2>
      <p class="section-subtitle">强大的AI驱动分析能力，全方位投资决策支持</p>
    </div>
    <div class="features-grid">
      <div v-for="item in FEATURES" :key="item.title" class="feature-card">
        <div class="feature-header">
          <div :class="['feature-icon', item.variant]">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <h3>{{ item.title }}</h3>
        </div>
        <p>{{ item.desc }}</p>
        <div class="feature-tags">
          <el-tag v-for="tag in item.tags" :key="tag" size="small" :type="tagType(item.variant)">
            {{ tag }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { FEATURES } from '../constants'
import type { FeatureItem } from '../constants'

const tagType = (variant: FeatureItem['variant']): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  if (variant === 'primary') return 'primary'
  return variant
}
</script>

<style lang="scss" scoped>
.features-section {
  margin-bottom: 64px;

  .section-header {
    text-align: center;
    margin-bottom: 40px;

    .section-title {
      font-size: 32px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      margin: 0 0 12px;
    }

    .section-subtitle {
      font-size: 16px;
      color: var(--el-text-color-regular);
      margin: 0;
    }
  }

  .features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 20px;
  }

  .feature-card {
    background: var(--el-bg-color);
    border-radius: 14px;
    padding: 28px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    border: 1px solid var(--el-border-color-lighter);
    transition: transform 0.3s, box-shadow 0.3s;
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
      background: linear-gradient(90deg, var(--el-color-primary), var(--el-color-success));
    }

    &:hover {
      transform: translateY(-6px);
      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.1);
    }

    .feature-header {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 14px;

      .feature-icon {
        width: 48px;
        height: 48px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        color: white;
        flex-shrink: 0;

        &.primary { background: linear-gradient(135deg, var(--el-color-primary), #b8943f); }
        &.success { background: linear-gradient(135deg, var(--el-color-success), #52c41a); }
        &.warning { background: linear-gradient(135deg, var(--el-color-warning), #faad14); }
        &.info { background: linear-gradient(135deg, var(--el-color-info), #1890ff); }
        &.danger { background: linear-gradient(135deg, var(--el-color-danger), #ff4d4f); }
      }

      h3 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    p {
      color: var(--el-text-color-regular);
      line-height: 1.6;
      margin: 0 0 16px;
      font-size: 14px;
    }

    .feature-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;

      .el-tag { border-radius: 12px; border: none; }
    }
  }
}

@media (max-width: 768px) {
  .features-section {
    .section-header .section-title { font-size: 26px; }
    .features-grid { grid-template-columns: 1fr; }
  }
}
</style>
