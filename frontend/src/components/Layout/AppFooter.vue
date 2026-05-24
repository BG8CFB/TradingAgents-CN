<template>
  <div class="app-footer">
    <div class="footer-content">
      <!-- 左侧：版权信息 -->
      <div class="footer-left">
        <span class="copyright">© 2025 TradingAgents-CN v1.0.0-preview</span>
      </div>

      <!-- 中间：免责提示 (悬浮显示完整版) -->
      <div class="footer-center">
        <el-tooltip
          placement="top"
          effect="dark"
          popper-class="disclaimer-tooltip"
        >
          <template #content>
            <div style="max-width: 400px; line-height: 1.6; font-size: 13px;">
              TradingAgents-CN 是一个 AI 多智能体股票分析辅助工具，不具备证券投资咨询资质。平台中的所有分析结果、评分、参考意见均由 AI 基于历史数据自动生成，仅供学习、研究与技术交流使用，不构成任何投资建议或决策依据。股票投资存在市场风险，可能导致本金损失。市场有风险，投资需谨慎。
            </div>
          </template>
          <div class="disclaimer-brief">
            <el-icon><InfoFilled /></el-icon>
            分析结果仅供参考，不构成投资建议
          </div>
        </el-tooltip>
      </div>

      <!-- 右侧：开源链接 -->
      <div class="footer-right">
        <a href="https://github.com/BG8CFB/TradingAgents-CN" target="_blank" rel="noopener noreferrer" class="footer-link">
          <el-icon><Link /></el-icon> GitHub
        </a>
        <span class="divider">|</span>
        <a href="https://github.com/TauricResearch/TradingAgents" target="_blank" rel="noopener noreferrer" class="footer-link">
          <el-icon><Star /></el-icon> Original
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Link, Star, InfoFilled } from '@element-plus/icons-vue'
</script>

<style lang="scss" scoped>
.app-footer {
  width: 100%;
  
  .footer-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: var(--el-text-color-regular);
    font-size: 13px;
    padding: 0 16px;
    height: 100%;
  }

  .footer-left {
    flex: 1;
    display: flex;
    justify-content: flex-start;
    color: var(--el-text-color-secondary);
  }

  .footer-center {
    flex: 1;
    display: flex;
    justify-content: center;

    .disclaimer-brief {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--el-text-color-placeholder);
      cursor: help;
      transition: color 0.3s;
      font-size: 12px;

      &:hover {
        color: var(--el-text-color-regular);
      }
    }
  }

  .footer-right {
    flex: 1;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;

    .divider {
      color: var(--el-border-color-lighter);
      font-size: 12px;
    }

    .footer-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: var(--el-text-color-secondary);
      text-decoration: none;
      transition: color 0.3s ease;

      &:hover {
        color: var(--el-color-primary);
      }
    }
  }
}

// 响应式设计：移动端改为纵向紧凑排版
@media (max-width: 768px) {
  .app-footer .footer-content {
    flex-direction: column;
    justify-content: center;
    gap: 12px;
    padding: 16px 0;
    
    .footer-left, .footer-center, .footer-right {
      flex: none;
      justify-content: center;
    }
  }
}
</style>

