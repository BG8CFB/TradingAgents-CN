<template>
  <div class="project-info-section">
    <div class="section-header">
      <h2 class="section-title">关于项目</h2>
      <p class="section-subtitle">开源免费，社区驱动</p>
    </div>

    <div class="project-cards">
      <div
        v-for="link in PROJECT_LINKS"
        :key="link.title"
        :class="['project-card', `project-card--${link.variant}`]"
      >
        <div class="project-card__header">
          <div :class="['project-card__icon', `project-card__icon--${link.variant}`]">
            <el-icon><component :is="link.icon" /></el-icon>
          </div>
          <div class="project-card__info">
            <h3>{{ link.title }}</h3>
            <a :href="link.url" target="_blank" rel="noopener noreferrer" class="project-card__link">
              <el-icon><Link /></el-icon>
              {{ link.url.replace('https://github.com/', '') }}
            </a>
          </div>
        </div>
        <p class="project-card__desc">{{ link.description }}</p>
        <ul class="project-card__highlights">
          <li v-for="h in link.highlights" :key="h">
            <el-icon class="check-icon"><CircleCheck /></el-icon>
            <span>{{ h }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Link, CircleCheck } from '@element-plus/icons-vue'
import { PROJECT_LINKS } from '../constants'
</script>

<style lang="scss" scoped>
.project-info-section {
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

  .project-cards {
    display: grid;
    grid-template-columns: 1fr;
    gap: 24px;
    max-width: 720px;
    margin: 0 auto;
  }

  .project-card {
    background: var(--el-bg-color);
    border-radius: 14px;
    padding: 32px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    border: 1px solid var(--el-border-color-lighter);
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
    }

    &--primary::before {
      background: linear-gradient(90deg, var(--el-color-primary), #9E7E3E);
    }

    &--success::before {
      background: linear-gradient(90deg, #7CB342, #A8CC5C);
    }

    &__header {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--el-border-color-lighter);
    }

    &__icon {
      width: 52px;
      height: 52px;
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      color: white;
      flex-shrink: 0;

      &--primary { background: linear-gradient(135deg, var(--el-color-primary), #9E7E3E); }
      &--success { background: linear-gradient(135deg, #7CB342, #A8CC5C); }
    }

    &__info {
      h3 {
        margin: 0 0 6px;
        font-size: 18px;
        font-weight: 700;
        color: var(--el-text-color-primary);
      }
    }

    &__link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: var(--el-color-primary);
      text-decoration: none;
      font-size: 13px;
      font-weight: 500;
      transition: color 0.3s;

      .el-icon { font-size: 13px; }
      &:hover { text-decoration: underline; }
    }

    &__desc {
      color: var(--el-text-color-regular);
      line-height: 1.7;
      margin: 0 0 18px;
      font-size: 14px;
    }

    &__highlights {
      list-style: none;
      padding: 0;
      margin: 0;

      li {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 6px 0;
        color: var(--el-text-color-regular);
        line-height: 1.5;
        font-size: 13px;

        .check-icon {
          color: var(--el-color-success);
          font-size: 16px;
          margin-top: 2px;
          flex-shrink: 0;
        }
      }
    }
  }
}

@media (max-width: 768px) {
  .project-info-section {
    .section-header .section-title { font-size: 26px; }
    .project-cards { grid-template-columns: 1fr; }
  }
}
</style>
