<template>
  <div class="hero-section">
    <div class="hero-content">
      <div class="hero-text">
        <h1 class="hero-title">
          TradingAgents-CN
          <span class="version-badge">{{ APP_VERSION }}</span>
        </h1>
        <p class="hero-subtitle">现代化的多智能体股票分析学习平台</p>
        <div class="hero-notice">
          <el-icon><InfoFilled /></el-icon>
          <span>
            本项目由 <strong>BG8CFB</strong> 维护，每周定期更新。永久免费，仅供学习研究使用。
            不具备证券投资咨询资质，不构成任何投资建议。严禁用于非法用途。
          </span>
        </div>
        <div class="hero-acknowledgment">
          <el-icon><Star /></el-icon>
          <a href="https://github.com/BG8CFB/TradingAgents-CN" target="_blank" rel="noopener noreferrer">
            GitHub 仓库
          </a>
          <span class="ack-sep">·</span>
          <span>Star 是最大的支持</span>
        </div>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="$router.push('/analysis/single')">
            <el-icon><TrendCharts /></el-icon>
            开始分析
          </el-button>
          <el-button size="large" @click="openDocs">
            <el-icon><Document /></el-icon>
            查看文档
          </el-button>
        </div>
      </div>
      <div class="hero-stats-card">
        <div class="stat-item">
          <div class="stat-number">{{ APP_VERSION }}</div>
          <div class="stat-label">当前版本</div>
        </div>
        <el-divider direction="vertical" />
        <div class="stat-item">
          <div class="stat-number">{{ formattedBuildTime }}</div>
          <div class="stat-label">构建时间</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { TrendCharts, Document, Star, InfoFilled } from '@element-plus/icons-vue'
import { APP_VERSION, BUILD_TIME } from '../constants'
import dayjs from 'dayjs'

const formattedBuildTime = computed(() => dayjs(BUILD_TIME).format('YYYY-MM-DD'))

const openDocs = () => {
  window.open('https://mp.weixin.qq.com/s/ppsYiBncynxlsfKFG8uEbw', '_blank')
}
</script>

<style lang="scss" scoped>
.hero-section {
  background: linear-gradient(135deg, var(--el-color-primary) 0%, #9E7E3E 100%);
  border-radius: 16px;
  padding: 48px 40px;
  margin-bottom: 48px;
  color: white;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><pattern id="g" width="100" height="100" patternUnits="userSpaceOnUse"><circle cx="25" cy="25" r="1" fill="white" opacity="0.08"/><circle cx="75" cy="75" r="1" fill="white" opacity="0.08"/></pattern></defs><rect width="100" height="100" fill="url(%23g)"/></svg>');
    pointer-events: none;
  }

  .hero-content {
    display: flex;
    align-items: center;
    gap: 48px;
    position: relative;
    z-index: 1;
  }

  .hero-text {
    flex: 1;

    .hero-title {
      font-size: 42px;
      font-weight: 700;
      margin: 0 0 12px;
      line-height: 1.2;

      .version-badge {
        display: inline-block;
        background: rgba(255, 255, 255, 0.2);
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 14px;
        font-weight: 500;
        margin-left: 12px;
        vertical-align: middle;
      }
    }

    .hero-subtitle {
      font-size: 20px;
      font-weight: 500;
      margin: 0 0 16px;
      opacity: 0.9;
    }

    .hero-notice {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      font-size: 14px;
      line-height: 1.6;
      opacity: 0.85;
      margin-bottom: 12px;
      max-width: 560px;

      .el-icon { margin-top: 3px; flex-shrink: 0; }
      strong { opacity: 1; }
    }

    .hero-acknowledgment {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      opacity: 0.9;
      margin-bottom: 28px;
      padding: 10px 14px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      width: fit-content;

      .el-icon { font-size: 16px; color: #ffd700; }

      a {
        color: white;
        text-decoration: none;
        font-weight: 500;
        border-bottom: 1px solid rgba(255, 255, 255, 0.3);
        transition: border-color 0.3s;

        &:hover { border-bottom-color: white; }
      }
    }

    .hero-actions {
      display: flex;
      gap: 14px;

      .el-button {
        padding: 10px 22px;
        font-size: 15px;
        border-radius: 8px;
      }

      .el-button--primary {
        background: white;
        color: var(--el-color-primary);
        border: none;

        &:hover { background: rgba(255, 255, 255, 0.9); transform: translateY(-2px); }
      }

      .el-button:not(.el-button--primary) {
        background: rgba(255, 255, 255, 0.1);
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.3);
        backdrop-filter: blur(10px);

        &:hover { background: rgba(255, 255, 255, 0.2); transform: translateY(-2px); }
      }
    }
  }

  .hero-stats-card {
    background: rgba(255, 255, 255, 0.12);
    backdrop-filter: blur(20px);
    border-radius: 16px;
    padding: 28px 36px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    display: flex;
    align-items: center;
    gap: 28px;
    flex-shrink: 0;

    .el-divider { border-color: rgba(255, 255, 255, 0.25); height: 48px; }

    .stat-item {
      text-align: center;

      .stat-number {
        font-size: 22px;
        font-weight: 700;
        margin-bottom: 6px;
        white-space: nowrap;
      }

      .stat-label {
        font-size: 13px;
        opacity: 0.75;
      }
    }
  }
}

@media (max-width: 768px) {
  .hero-section {
    padding: 36px 24px;

    .hero-content {
      flex-direction: column;
      gap: 24px;
      text-align: center;
    }

    .hero-text {
      .hero-title {
        font-size: 32px;
        .version-badge { display: block; margin: 12px auto 0; width: fit-content; }
      }
      .hero-subtitle { font-size: 18px; }
      .hero-notice { margin-left: auto; margin-right: auto; }
      .hero-acknowledgment { margin-left: auto; margin-right: auto; }
      .hero-actions { justify-content: center; flex-wrap: wrap; }
    }

    .hero-stats-card {
      width: 100%;
      justify-content: center;
    }
  }
}

@media (max-width: 480px) {
  .hero-section {
    padding: 28px 18px;

    .hero-text {
      .hero-title { font-size: 26px; }
      .hero-subtitle { font-size: 16px; }
      .hero-actions .el-button { padding: 8px 16px; font-size: 14px; }
    }

    .hero-stats-card {
      padding: 20px 16px;
      gap: 16px;
      .stat-item .stat-number { font-size: 18px; }
    }
  }
}
</style>
