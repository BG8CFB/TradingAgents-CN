<template>
  <div class="contact-footer">
    <div class="contact-section">
      <div class="section-header">
        <h2 class="section-title">联系我们</h2>
        <p class="section-subtitle">获取支持、反馈问题或加入社区讨论</p>
      </div>
      <div class="contact-grid">
        <div v-for="c in CONTACTS" :key="c.title" class="contact-card">
          <div :class="['contact-icon', c.variant]">
            <el-icon><component :is="c.icon" /></el-icon>
          </div>
          <h4>{{ c.title }}</h4>
          <p v-if="c.link">
            <a :href="c.link" target="_blank" rel="noopener noreferrer" class="doc-link">
              {{ c.content }}
            </a>
          </p>
          <p v-else>{{ c.content }}</p>
          <span class="contact-desc">{{ c.desc }}</span>
        </div>
      </div>
    </div>

    <div class="footer-section">
      <p>&copy; {{ year }} TradingAgents-CN. All rights reserved.</p>
      <p>本工具为免费学习研究工具，不具备证券投资咨询资质，不构成任何投资建议。开源组件遵循 Apache 2.0；前端与后端采用专有许可证（个人学习/研究免费，商业使用需授权）。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CONTACTS } from '../constants'

const year = new Date().getFullYear()
</script>

<style lang="scss" scoped>
.contact-footer {
  .contact-section {
    margin-bottom: 48px;

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

    .contact-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 20px;
    }

    .contact-card {
      background: var(--el-bg-color);
      border-radius: 14px;
      padding: 28px;
      text-align: center;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
      border: 1px solid var(--el-border-color-lighter);
      transition: transform 0.3s, box-shadow 0.3s;

      &:hover {
        transform: translateY(-4px);
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.1);
      }

      .contact-icon {
        width: 56px;
        height: 56px;
        border-radius: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 18px;
        font-size: 22px;
        color: white;

        &.qq { background: linear-gradient(135deg, #B8A070, #C5A55A); }
        &.email { background: linear-gradient(135deg, #E57373, #C5A55A); }
        &.wechat { background: linear-gradient(135deg, #7CB342, #A8CC5C); }
        &.docs { background: linear-gradient(135deg, var(--el-color-primary), #9E7E3E); }
      }

      h4 {
        margin: 0 0 10px;
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      p {
        margin: 0 0 6px;
        font-size: 14px;
        font-weight: 500;
        color: var(--el-text-color-primary);

        .doc-link {
          color: var(--el-color-primary);
          text-decoration: none;
          &:hover { text-decoration: underline; }
        }
      }

      .contact-desc {
        font-size: 13px;
        color: var(--el-text-color-regular);
      }
    }
  }

  .footer-section {
    text-align: center;
    padding: 32px 0 16px;
    border-top: 1px solid var(--el-border-color-extra-light);
    color: var(--el-text-color-regular);

    p {
      margin: 6px 0;
      font-size: 13px;
    }
  }
}

@media (max-width: 768px) {
  .contact-footer {
    .contact-section {
      .section-header .section-title { font-size: 26px; }
      .contact-grid { grid-template-columns: 1fr; }
    }
  }
}
</style>
