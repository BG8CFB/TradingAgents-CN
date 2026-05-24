<template>
  <div class="tech-section">
    <div class="section-header">
      <h2 class="section-title">技术架构</h2>
      <p class="section-subtitle">现代化的技术栈，确保系统的稳定性和可扩展性</p>
    </div>
    <div class="tech-stack">
      <div v-for="cat in TECH_STACK" :key="cat.title" class="tech-category">
        <div class="tech-header">
          <div :class="['tech-icon', cat.variant]">
            <el-icon><component :is="cat.icon" /></el-icon>
          </div>
          <h3>{{ cat.title }}</h3>
        </div>
        <div class="tech-list">
          <div v-for="item in cat.items" :key="item.name" class="tech-item">
            <span class="tech-name">{{ item.name }}</span>
            <span class="tech-desc">{{ item.desc }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { TECH_STACK } from '../constants'
</script>

<style lang="scss" scoped>
.tech-section {
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

  .tech-stack {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 24px;
  }

  .tech-category {
    background: var(--el-bg-color);
    border-radius: 14px;
    padding: 28px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    border: 1px solid var(--el-border-color-lighter);
    transition: transform 0.3s, box-shadow 0.3s;

    &:hover {
      transform: translateY(-4px);
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.1);
    }

    .tech-header {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 20px;

      .tech-icon {
        width: 44px;
        height: 44px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        color: white;

        &.frontend { background: linear-gradient(135deg, #7CB342, #6B6358); }
        &.backend { background: linear-gradient(135deg, #E57373, #C5A55A); }
        &.ai { background: linear-gradient(135deg, #C5A55A, #7CB342); }
      }

      h3 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    .tech-list {
      .tech-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--el-border-color-extra-light);

        &:last-child { border-bottom: none; }

        .tech-name {
          font-weight: 500;
          color: var(--el-text-color-primary);
          font-size: 14px;
        }

        .tech-desc {
          font-size: 13px;
          color: var(--el-text-color-regular);
        }
      }
    }
  }
}

@media (max-width: 768px) {
  .tech-section {
    .section-header .section-title { font-size: 26px; }
    .tech-stack { grid-template-columns: 1fr; }
  }
}
</style>
