<template>
  <div class="app-footer">
    <div class="footer-content">
      <div class="copyright">
        <span>© 2025 TradingAgents-CN v1.0.0-preview</span>
        <span class="rights">All rights reserved.</span>
      </div>
      <div class="footer-links">
        <a href="https://github.com/BG8CFB/TradingAgents-CN"
           target="_blank"
           rel="noopener noreferrer"
           class="footer-link">
          <el-icon><Link /></el-icon>
          GitHub
        </a>
        <a href="https://github.com/TauricResearch/TradingAgents"
           target="_blank"
           rel="noopener noreferrer"
           class="footer-link">
          <el-icon><Star /></el-icon>
          Original Project
        </a>
      </div>
      <div class="disclaimer-text">
        TradingAgents-CN 是一个 AI 多智能体股票分析辅助工具，不具备证券投资咨询资质。平台中的所有分析结果、评分、参考意见均由 AI 基于历史数据自动生成，仅供学习、研究与技术交流使用，不构成任何投资建议或决策依据。股票投资存在市场风险、流动性风险、政策风险等多种风险，可能导致本金损失。用户应基于自身风险承受能力独立决策，使用本工具产生的任何投资行为及其后果由用户自行承担。市场有风险，投资需谨慎。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Footer组件逻辑
import { Link, Star } from '@element-plus/icons-vue'
</script>

<style lang="scss" scoped>
.app-footer {
  .footer-content {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 6px;
    color: var(--el-text-color-regular);
    font-size: 14px;
    padding: 12px 16px;
    text-align: center;
  }

  .copyright {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .footer-links {
    display: flex;
    align-items: center;
    gap: 20px;
    margin-top: 4px;

    .footer-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: var(--el-color-primary);
      text-decoration: none;
      font-size: 13px;
      transition: all 0.3s ease;
      padding: 2px 8px;
      border-radius: 4px;

      .el-icon {
        font-size: 14px;
      }

      &:hover {
        background-color: var(--el-color-primary-light-9);
        color: var(--el-color-primary-dark-2);
        transform: translateY(-1px);
      }
    }
  }

  .rights {
    margin-left: 4px;
  }

  .disclaimer-text {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    line-height: 1.6;
    max-width: 1100px;
  }
}

// 响应式设计
@media (max-width: 480px) {
  .app-footer {
    .footer-content {
      padding: 10px 12px;
    }

    .copyright {
      flex-direction: column;
      gap: 2px;
      font-size: 12px;
    }

    .footer-links {
      gap: 12px;
      flex-wrap: wrap;
      justify-content: center;

      .footer-link {
        font-size: 12px;
        padding: 2px 6px;
      }
    }

    .disclaimer-text {
      font-size: 11px;
      max-width: 100%;
    }
  }
}
</style>

