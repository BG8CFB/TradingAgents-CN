<template>
  <div class="single-analysis">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><Document /></el-icon>
            单股分析
          </h1>
          <p class="page-description">
            AI驱动的智能股票分析，多维度评估投资价值与风险
          </p>
        </div>
      </div>
    </div>

    <!-- 主要分析表单 -->
    <div class="analysis-container">
      <el-row :gutter="24">
        <!-- 左侧：基础配置 -->
        <el-col :span="18">
          <el-card class="main-form-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>分析配置</h3>
                <el-tag type="info" size="small">必填信息</el-tag>
              </div>
            </template>

            <el-form :model="analysisForm" label-width="100px" class="analysis-form">
              <!-- 股票信息 -->
              <div class="form-section">
                <h4 class="section-title">📊 股票信息</h4>
                <el-row :gutter="16">
                  <el-col :span="12">
                    <el-form-item label="股票代码" required>
                      <el-input
                        v-model="analysisForm.stockCode"
                        placeholder="如：000001、AAPL、700、1810"
                        clearable
                        size="large"
                        class="stock-input"
                        :class="{ 'is-error': stockCodeError }"
                        @blur="validateStockCodeInput"
                        @input="onStockCodeInput"
                      >
                        <template #prefix>
                          <el-icon><TrendCharts /></el-icon>
                        </template>
                      </el-input>
                      <div v-if="stockCodeError" class="error-message">
                        <el-icon><WarningFilled /></el-icon>
                        {{ stockCodeError }}
                      </div>
                      <div v-else-if="stockCodeHelp" class="help-message">
                        <el-icon><InfoFilled /></el-icon>
                        {{ stockCodeHelp }}
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="市场类型">
                      <el-select
                        v-model="analysisForm.market"
                        placeholder="选择市场"
                        size="large"
                        style="width: 100%"
                        @change="onMarketChange"
                      >
                        <el-option label="🇨🇳 A股市场" value="A股">
                          <span>🇨🇳 A股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（6位数字）</span>
                        </el-option>
                        <el-option label="🇺🇸 美股市场" value="美股">
                          <span>🇺🇸 美股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（1-5个字母）</span>
                        </el-option>
                        <el-option label="🇭🇰 港股市场" value="港股">
                          <span>🇭🇰 港股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（1-5位数字）</span>
                        </el-option>
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-form-item label="分析日期">
                  <el-date-picker
                    v-model="analysisForm.analysisDate"
                    type="date"
                    placeholder="选择分析基准日期"
                    size="large"
                    style="width: 100%"
                    :disabled-date="disabledDate"
                  />
                </el-form-item>
              </div>

              <!-- 分析师团队 -->
              <div class="form-section">
                <h4 class="section-title">👥 分析师团队</h4>
                <div class="analysts-grid">
                  <div
                    v-for="analyst in analysts"
                    :key="analyst.id"
                    class="analyst-card"
                    :class="{ 
                      active: analysisForm.selectedAnalysts.includes(analyst.id)
                    }"
                    @click="toggleAnalyst(analyst.id)"
                  >
                    <div class="analyst-avatar">
                      <el-icon>
                        <component :is="resolveIcon(analyst.icon)" />
                      </el-icon>
                    </div>
                    <div class="analyst-content">
                      <div class="analyst-name">{{ analyst.name }}</div>
                      <div class="analyst-desc">{{ analyst.description }}</div>
                    </div>
                    <div class="analyst-check">
                      <el-icon v-if="analysisForm.selectedAnalysts.includes(analyst.id)" class="check-icon">
                        <Check />
                      </el-icon>
                    </div>
                  </div>
                </div>
                

              </div>

              <!-- 后续阶段配置 -->
              <div class="form-section">
                <div class="section-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                  <h4 class="section-title" style="margin: 0;">🚀 深度分析阶段</h4>
                  <div class="time-estimate" style="display: flex; align-items: center; gap: 6px; font-size: 14px; background: var(--el-color-success-light-9); padding: 4px 12px; border-radius: 12px; color: var(--el-color-success);">
                    <el-icon><Timer /></el-icon>
                    <span>预计总耗时: <strong>{{ estimatedTotalTime }}</strong> 分钟</span>
                  </div>
                </div>
                
                <div class="phases-grid">
                  <div 
                    v-for="phase in PHASES" 
                    :key="phase.id" 
                    class="phase-card"
                    :class="{ enabled: getPhaseConfig(phase.name)?.enabled }"
                  >
                    <div class="phase-header">
                      <div class="phase-title-row">
                        <div class="phase-title">{{ phase.title }}</div>
                        <el-switch
                          :model-value="getPhaseConfig(phase.name)?.enabled"
                          @update:model-value="(val: boolean | string | number) => { if (getPhaseConfig(phase.name)) getPhaseConfig(phase.name).enabled = val as boolean }"
                          :disabled="phase.id === 4"
                        />
                      </div>
                      <div class="phase-desc">{{ phase.description }}</div>
                    </div>

                    <div class="phase-body" v-if="getPhaseConfig(phase.name)?.enabled">
                      <div class="phase-agents">
                        <span class="label">参与角色:</span>
                        <div class="agent-tags">
                          <el-tag v-for="agent in phase.agents" :key="agent" size="small" type="info" effect="plain">
                            {{ agent }}
                          </el-tag>
                        </div>
                      </div>

                      <!-- 第四阶段固定执行1次，不显示辩论轮次设置 -->
                      <div class="phase-rounds" v-if="phase.hasDebateRounds !== false">
                        <span class="label">辩论轮次:</span>
                        <el-input-number
                          :model-value="getPhaseConfig(phase.name)?.debateRounds"
                          @update:model-value="(val: number | undefined) => { if (getPhaseConfig(phase.name)) getPhaseConfig(phase.name).debateRounds = val || 1 }"
                          :min="phase.minRounds"
                          :max="phase.maxRounds"
                          size="small"
                          controls-position="right"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="form-section">
                <div class="action-buttons" style="display: flex; justify-content: center; align-items: center; width: 100%; text-align: center;">
                  <el-button
                    v-if="analysisStatus === 'idle'"
                    type="primary"
                    size="large"
                    @click="submitAnalysis"
                    :loading="submitting"
                    :disabled="!analysisForm.stockCode.trim()"
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><TrendCharts /></el-icon>
                    开始智能分析
                  </el-button>

                  <el-button
                    v-else-if="analysisStatus === 'running'"
                    type="warning"
                    size="large"
                    disabled
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><Loading /></el-icon>
                    分析进行中...
                  </el-button>

                  <div v-else-if="analysisStatus === 'completed'" style="display: flex; gap: 12px;">
                    <el-button
                      type="success"
                      size="large"
                      @click="showResults = !showResults"
                      class="submit-btn"
                      style="width: 180px; height: 56px; font-size: 16px; font-weight: 700; border-radius: 16px;"
                    >
                      <el-icon><Document /></el-icon>
                      {{ showResults ? '隐藏结果' : '查看结果' }}
                    </el-button>

                    <el-button
                      type="primary"
                      size="large"
                      @click="restartAnalysis"
                      class="submit-btn"
                      style="width: 180px; height: 56px; font-size: 16px; font-weight: 700; border-radius: 16px;"
                    >
                      <el-icon><Refresh /></el-icon>
                      重新分析
                    </el-button>
                  </div>

                  <el-button
                    v-else-if="analysisStatus === 'failed'"
                    type="danger"
                    size="large"
                    @click="restartAnalysis"
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><Refresh /></el-icon>
                    重新分析
                  </el-button>
                </div>
              </div>

              <!-- 分析进度显示 -->
              <div v-if="analysisStatus === 'running'" class="progress-section">
                <el-card class="progress-card" shadow="hover">
                  <template #header>
                    <div class="progress-header">
                      <h4>
                        <el-icon class="rotating-icon">
                          <Loading />
                        </el-icon>
                        分析进行中...
                      </h4>
                      <!-- 任务ID已隐藏 -->
                      <!-- <el-tag type="warning">{{ currentTaskId }}</el-tag> -->
                    </div>
                  </template>

                  <div class="progress-content">
                    <!-- 总体进度信息 -->
                    <div class="overall-progress-info">
                      <div class="progress-stats">
                        <!-- 当前步骤已隐藏 -->
                        <!--
                        <div class="stat-item">
                          <div class="stat-label">当前步骤</div>
                          <div class="stat-value">{{ progressInfo.currentStep || '初始化中...' }}</div>
                        </div>
                        -->
                        <!-- 整体进度已隐藏 -->
                        <!--
                        <div class="stat-item">
                          <div class="stat-label">整体进度</div>
                          <div class="stat-value">{{ progressInfo.progress.toFixed(1) }}%</div>
                        </div>
                        -->
                        <div class="stat-item">
                          <div class="stat-label">已用时间</div>
                          <div class="stat-value">{{ formatTime(progressInfo.elapsedTime) }}</div>
                        </div>
                        <div class="stat-item">
                          <div class="stat-label">预计剩余</div>
                          <div class="stat-value">{{ formatTime(progressInfo.remainingTime) }}</div>
                        </div>
                        <div class="stat-item">
                          <div class="stat-label">预计总时长</div>
                          <div class="stat-value">{{ formatTime(progressInfo.totalTime) }}</div>
                        </div>
                      </div>
                    </div>

                    <!-- 进度条 -->
                    <div class="progress-bar-section">
                      <el-progress
                        :percentage="Math.round(progressInfo.progress)"
                        :stroke-width="12"
                        :show-text="true"
                        :status="getProgressStatus()"
                        class="main-progress-bar"
                      />
                    </div>

                    <!-- 当前任务详情 -->
                    <div class="current-task-info">
                      <div class="task-title">
                        <el-icon class="task-icon">
                          <Loading />
                        </el-icon>
                        {{ progressInfo.currentStep || '正在初始化分析引擎...' }}
                      </div>
                      <div
                        class="task-description"
                        style="white-space: pre-wrap; line-height: 1.6;"
                      >
                        {{ progressInfo.currentStepDescription || progressInfo.message || 'AI正在根据您的要求重点分析相关内容' }}
                      </div>
                    </div>

                    <!-- 分析步骤显示 - 已隐藏 -->
                    <!--
                    <div v-if="analysisSteps.length > 0" class="analysis-steps">
                      <h5 class="steps-title">📋 分析步骤</h5>
                      <div class="steps-container">
                        <div
                          v-for="(step, index) in analysisSteps"
                          :key="index"
                          class="step-item"
                          :class="{
                            'step-completed': step.status === 'completed',
                            'step-current': step.status === 'current',
                            'step-pending': step.status === 'pending'
                          }"
                        >
                          <div class="step-icon">
                            <el-icon v-if="step.status === 'completed'" class="completed-icon">
                              <Check />
                            </el-icon>
                            <el-icon v-else-if="step.status === 'current'" class="current-icon rotating-icon">
                              <Loading />
                            </el-icon>
                            <el-icon v-else class="pending-icon">
                              <Clock />
                            </el-icon>
                          </div>
                          <div class="step-content">
                            <div class="step-title">{{ step.title }}</div>
                            <div class="step-description">{{ step.description }}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                    -->
                  </div>
                </el-card>
              </div>
            </el-form>
          </el-card>
        </el-col>

        <!-- 右侧：高级配置 -->
        <el-col :span="6">
          <el-card class="config-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>高级配置</h3>
                <el-tag type="warning" size="small">可选设置</el-tag>
              </div>
            </template>

            <div class="config-content">
              <!-- AI模型配置 -->
              <div class="config-section">
                <h4 class="config-title">🤖 AI模型配置</h4>
                <div class="model-config">
                  <div class="model-item">
                    <div class="model-label">
                      <span>分析师模型（一阶段）</span>
                      <el-tooltip content="用于一阶段分析师（市场分析、新闻分析、基本面分析等），推荐选择低幻觉、数字敏感的模型" placement="top">
                        <el-icon class="help-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-select v-model="modelSettings.analystModel" size="small" style="width: 100%" filterable>
                      <el-option
                        v-for="model in availableModels"
                        :key="`quick-${model.provider}/${model.model_name}`"
                        :label="model.model_display_name || model.model_name"
                        :value="model.model_name"
                      >
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                          <span style="flex: 1;">{{ model.model_display_name || model.model_name }}</span>
                          <div style="display: flex; align-items: center; gap: 4px;">
                            <!-- 能力等级徽章 -->
                            <el-tag
                              v-if="model.capability_level"
                              :type="getCapabilityTagType(model.capability_level)"
                              size="small"
                              effect="plain"
                            >
                              {{ getCapabilityText(model.capability_level) }}
                            </el-tag>
                            <!-- 角色标签 -->
                            <el-tag
                              v-if="isAnalystRole(model.suitable_roles)"
                              type="success"
                              size="small"
                              effect="plain"
                            >
                              ⚡分析师
                            </el-tag>
                            <span style="font-size: 12px; color: #909399;">{{ model.provider }}</span>
                          </div>
                        </div>
                      </el-option>
                    </el-select>
                  </div>

                  <div class="model-item">
                    <div class="model-label">
                      <span>辩论推理模型（二至四阶段）</span>
                      <el-tooltip content="用于二至四阶段（辩论、风控、交易决策），推荐选择强逻辑推理能力的模型" placement="top">
                        <el-icon class="help-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <DeepModelSelector v-model="modelSettings.debateModel" :available-models="availableModels" type="debate" size="small" width="100%" />
                  </div>
                </div>
              </div>

              <!-- 分析选项 -->
              <div class="config-section">
                <h4 class="config-title">⚙️ 分析选项</h4>
                <div class="option-list">
                  <div class="option-item">
                    <div class="option-info">
                      <span class="option-name">语言偏好</span>
                    </div>
                    <el-select v-model="analysisForm.language" size="small" style="width: 100px">
                      <el-option label="中文" value="zh-CN" />
                      <el-option label="English" value="en-US" />
                    </el-select>
                  </div>
                </div>
              </div>

              <!-- MCP工具选择 (已移除，统一在设置中管理) -->
              <!-- <div class="config-section">
                <h4 class="config-title">🛠️ MCP工具</h4>
                 ...
              </div> -->

            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 分析结果显示 -->
      <div v-if="showResults && analysisResults" class="results-section">
        <el-row :gutter="24">
          <el-col :span="24">
            <el-card class="results-card" shadow="hover">
              <template #header>
                <div class="results-header">
                  <h3>📊 分析结果</h3>
                  <div class="result-meta">
                    <el-tag type="success">{{ analysisResults.symbol || analysisResults.stock_symbol || analysisForm.symbol || analysisForm.stockCode }}</el-tag>
                    <el-tag>{{ analysisResults.analysis_date }}</el-tag>
                    <el-tag v-if="analysisResults.model_info && analysisResults.model_info !== 'Unknown'" type="info">
                      <el-icon><Cpu /></el-icon>
                      {{ analysisResults.model_info }}
                    </el-tag>
                  </div>
                </div>
              </template>

              <div class="results-content">
                <!-- 风险提示 -->
                <div class="risk-disclaimer">
                  <el-alert
                    type="warning"
                    :closable="false"
                    show-icon
                  >
                    <template #title>
                      <div class="disclaimer-content">
                        <el-icon class="disclaimer-icon"><WarningFilled /></el-icon>
                        <div class="disclaimer-text">
                          <p style="margin: 0 0 8px 0;"><strong>⚠️ 重要风险提示与免责声明</strong></p>
                          <ul style="margin: 0; padding-left: 20px; line-height: 1.8;">
                            <li><strong>学习工具：</strong>本系统为股票分析学习研究工具，使用AI技术对公开市场数据进行分析，不具备证券投资咨询资质，不提供证券投资顾问服务。</li>
                            <li><strong>非投资建议：</strong>所有分析结果、评分、建议均由 AI 自动生成，仅供学习研究与技术交流，不构成任何买卖建议或投资决策依据。</li>
                            <li><strong>数据局限性：</strong>分析基于历史数据和公开信息，可能存在延迟、不完整或不准确的情况，无法预测未来市场走势。</li>
                            <li><strong>投资风险：</strong>股票投资存在市场风险、流动性风险、政策风险等多种风险，可能导致本金损失。</li>
                            <li><strong>独立决策：</strong>投资者应基于自身风险承受能力、投资目标和财务状况独立做出投资决策。</li>
                            <li><strong>专业咨询：</strong>重大投资决策建议咨询具有合法资质的专业投资顾问或金融机构。</li>
                            <li><strong>责任声明：</strong>使用本工具产生的任何投资决策及其后果由投资者自行承担，本系统不承担任何责任。</li>
                          </ul>
                        </div>
                      </div>
                    </template>
                  </el-alert>
                </div>

                <!-- 最终决策 -->
                <div v-if="analysisResults.structured_summary || analysisResults.decision" class="decision-section">
                  <h4>🎯 分析参考</h4>
                  <div class="decision-card">
                    <div class="decision-main">
                      <div class="decision-action">
                        <span class="label">分析倾向:</span>
                        <el-tag
                          :type="getActionTagType(analysisResults.structured_summary?.final_signal || analysisResults.decision?.action)"
                          size="large"
                        >
                          {{ analysisResults.structured_summary?.final_signal || analysisResults.decision?.action }}
                        </el-tag>
                        <el-tag type="info" size="small" style="margin-left: 8px;">仅供参考</el-tag>
                      </div>

                      <div class="decision-metrics">
                        <div class="metric-item">
                          <span class="label">参考价格:</span>
                          <span class="value">{{ analysisResults.structured_summary?.key_indicators?.target_price || analysisResults.decision?.target_price || '暂无' }}</span>
                        </div>
                        <div class="metric-item">
                          <span class="label">模型置信度:</span>
                          <span class="value">{{ analysisResults.structured_summary ? formatPercentage(analysisResults.structured_summary.model_confidence/100) : formatPercentage(analysisResults.decision?.confidence) }}</span>
                          <el-tooltip content="基于AI模型计算的置信度，不代表实际投资成功率" placement="top">
                            <el-icon style="margin-left: 4px; cursor: help;"><QuestionFilled /></el-icon>
                          </el-tooltip>
                        </div>
                        <div class="metric-item">
                          <span class="label">风险评分:</span>
                          <span class="value">{{ analysisResults.structured_summary?.risk_assessment?.level || formatPercentage(analysisResults.decision?.risk_score) }}</span>
                          <el-tooltip content="基于历史数据的风险评估，实际风险可能更高" placement="top">
                            <el-icon style="margin-left: 4px; cursor: help;"><QuestionFilled /></el-icon>
                          </el-tooltip>
                        </div>
                      </div>
                    </div>

                    <div class="decision-reasoning">
                      <h5>分析依据:</h5>
                      <p v-if="analysisResults.structured_summary && analysisResults.structured_summary.risk_assessment">
                        {{ analysisResults.structured_summary.risk_assessment.description }}
                      </p>
                      <p v-else>
                        {{ analysisResults.decision?.reasoning || analysisResults.decision?.reason || '暂无分析依据' }}
                      </p>
                      
                      <!-- 关键指标展示 -->
                      <div v-if="analysisResults.structured_summary && analysisResults.structured_summary.key_indicators" class="key-indicators">
                        <h5 class="key-indicators-title">🔑 关键点位参考:</h5>
                        <div class="key-indicators-grid">
                          <div class="key-indicator-item">
                            <span class="key-indicator-label">入场:</span>
                            <strong class="key-indicator-value">{{ analysisResults.structured_summary.key_indicators.entry_price }}</strong>
                          </div>
                          <div class="key-indicator-item">
                            <span class="key-indicator-label">止损:</span>
                            <strong class="key-indicator-value">{{ analysisResults.structured_summary.key_indicators.stop_loss }}</strong>
                          </div>
                          <div class="key-indicator-item">
                            <span class="key-indicator-label">支撑:</span>
                            <strong class="key-indicator-value">{{ analysisResults.structured_summary.key_indicators.support_level }}</strong>
                          </div>
                          <div class="key-indicator-item">
                            <span class="key-indicator-label">阻力:</span>
                            <strong class="key-indicator-value">{{ analysisResults.structured_summary.key_indicators.resistance_level }}</strong>
                          </div>
                        </div>
                      </div>

                      <el-alert type="info" :closable="false" style="margin-top: 12px;">
                        <template #default>
                          <span style="font-size: 13px;">💡 以上内容由 AI 基于历史数据自动生成，仅供学习研究，不构成任何投资建议。投资有风险，入市需谨慎。</span>
                        </template>
                      </el-alert>
                    </div>
                  </div>
                </div>

                <!-- 分析概览 -->
                <div v-if="analysisResults" class="overview-section">
                  <h4>📊 分析概览</h4>
                  <div class="overview-card">
  
                    <div v-if="analysisResults.structured_summary?.analysis_summary || analysisResults.summary" class="overview-summary">
                      <h5>分析摘要:</h5>
                      <p style="white-space: pre-wrap;">{{ analysisResults.structured_summary?.analysis_summary || analysisResults.summary }}</p>
                    </div>

                    <div v-if="analysisResults.structured_summary?.investment_recommendation || analysisResults.recommendation" class="overview-recommendation">
                      <h5>投资建议:</h5>
                      <p style="white-space: pre-wrap;">{{ analysisResults.structured_summary?.investment_recommendation || analysisResults.recommendation }}</p>
                    </div>
                  </div>
                </div>

                <!-- 详细分析报告 -->
                <div v-if="analysisResults.state || analysisResults.reports" class="reports-section">
                  <h4>📋 详细分析报告</h4>

                  <!-- 美观的标签页展示 -->
                  <div class="analysis-tabs-container">
                    <el-tabs
                      v-model="activeReportTab"
                      type="card"
                      class="analysis-tabs"
                      tab-position="top"
                      :key="analysisResults?.id || 'default'"
                    >
                      <el-tab-pane
                        v-for="(report, key) in getAnalysisReports(analysisResults)"
                        :key="key"
                        :name="key.toString()"
                        :label="report.title"
                        class="report-tab-pane"
                      >
                        <!-- 标签页内容头部 -->
                        <div class="report-header">
                          <div class="report-title">
                            <span class="report-icon">{{ getReportIcon(report.title) }}</span>
                            <span class="report-name">{{ getReportName(report.title) }}</span>
                          </div>
                          <div class="report-description">{{ getReportDescription(report.title) }}</div>
                        </div>

                        <!-- 报告内容 -->
                        <div class="report-content-wrapper">
                          <div
                            class="report-content"
                            v-html="formatReportContent(report.content)"
                            v-if="report.content"
                          ></div>
                          <div v-else class="no-content">
                            <el-empty description="暂无内容" />
                          </div>
                        </div>
                      </el-tab-pane>
                    </el-tabs>
                  </div>
                </div>

                <!-- 操作按钮 -->
                <div class="result-actions">
                  <el-dropdown trigger="click" @command="downloadReport">
                    <el-button type="primary">
                      <el-icon><Download /></el-icon>
                      下载报告
                      <el-icon class="el-icon--right"><arrow-down /></el-icon>
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="markdown">
                          <el-icon><document /></el-icon> Markdown
                        </el-dropdown-item>
                        <el-dropdown-item command="docx">
                          <el-icon><document /></el-icon> Word 文档
                        </el-dropdown-item>
                        <el-dropdown-item command="pdf">
                          <el-icon><document /></el-icon> PDF
                        </el-dropdown-item>
                        <el-dropdown-item command="json" divided>
                          <el-icon><document /></el-icon> JSON (原始数据)
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>

                <!-- 风险提示 -->
                <el-alert
                  type="warning"
                  :closable="false"
                  show-icon
                  class="risk-disclaimer"
                >
                  <template #title>
                    <span style="font-weight: bold;">报告由 AI 基于历史数据自动生成，仅供学习研究，不构成任何投资建议。市场有风险，投资需谨慎。</span>
                  </template>
                </el-alert>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Document,
  TrendCharts,
  InfoFilled,
  Check,
  Loading,
  Refresh,
  Download,
  WarningFilled,
  Cpu,
  QuestionFilled,
  ArrowDown,
  Timer,
  DataAnalysis,
  ChatDotRound,
  Histogram,
  Money,
  Wallet,
} from '@element-plus/icons-vue'
import { analysisApi, type SingleAnalysisRequest } from '@/api/analysis'
import { stocksApi } from '@/api/stocks'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { configApi } from '@/api/config'
import { agentConfigApi } from '@/api/agentConfigs'
import { mcpApi } from '@/api/mcp'
import { reportsApi } from '@/api/reports'
import type { MCPTool } from '@/types/mcp'
import DeepModelSelector from '@/components/DeepModelSelector.vue'
import { normalizeAnalystIds } from '@/constants/analysts'
import { PHASES, estimateTotalTime } from '@/constants/phases'
import { renderMarkdown } from '@/utils/markdown'
import { validateStockCode, getStockCodeFormatHelp } from '@/utils/stockValidator'
import { normalizeMarketForAnalysis, getMarketByStockCode } from '@/utils/market'

// 市场类型定义
type MarketType = 'A股' | '美股' | '港股'

// 分析师接口
interface Analyst {
  id: string
  name: string
  description: string
  icon: string
  slug: string
}

// 表单类型定义
interface AnalysisForm {
  stockCode: string
  symbol: string
  market: MarketType
  analysisDate: Date
  selectedAnalysts: string[]
  mcpTools: string[]
  language: 'zh-CN' | 'en-US'
  phases: {
    phase2: { enabled: boolean, debateRounds: number }
    phase3: { enabled: boolean, debateRounds: number }
    phase4: { enabled: boolean, debateRounds: number }
  }
}

// 使用store
const route = useRoute()

const submitting = ref(false)

// 分析进度和结果相关状态
const currentTaskId = ref('')
const analysisStatus = ref('idle') // 'idle', 'running', 'completed', 'failed'
const showResults = ref(false)
const analysisResults = ref<Record<string, any> | null>(null)
const activeReportTab = ref('') // 当前激活的报告标签页
const progressInfo = ref({
  progress: 0,
  currentStep: '',
  currentStepDescription: '',  // 当前步骤描述
  message: '',
  elapsedTime: 0,      // 已用时间（秒）
  remainingTime: 0,    // 预计剩余时间（秒）
  totalTime: 0         // 预计总时长（秒）
})
const pollingTimer = ref<ReturnType<typeof setTimeout> | null>(null)
let initialQueryTimer: ReturnType<typeof setTimeout> | null = null

// 动态分析师列表
const analysts = ref<Analyst[]>([])
const loadingAnalysts = ref(false)

// 分析师图标映射
const getAnalystIcon = (slug: string) => {
  const map: Record<string, string> = {
    'financial-news-analyst': 'Document',
    'china-market-analyst': 'TrendCharts',
    'market-analyst': 'Histogram',
    'social-media-analyst': 'ChatDotRound',
    'fundamentals-analyst': 'DataAnalysis',
    'short-term-capital-analyst': 'Wallet',
    'bull-researcher': 'TrendCharts',
    'bear-researcher': 'TrendCharts'
  }
  // 简单的启发式映射
  if (slug.includes('news')) return 'Document'
  if (slug.includes('market')) return 'TrendCharts'
  if (slug.includes('social')) return 'ChatDotRound'
  if (slug.includes('fund')) return 'DataAnalysis'
  if (slug.includes('capital')) return 'Wallet'
  
  return map[slug] || 'User'
}

// 获取分析师列表
const fetchAnalysts = async () => {
  loadingAnalysts.value = true
  try {
    const res = await agentConfigApi.getPhase(1)
    if (res.success && res.data && res.data.customModes) {
      analysts.value = res.data.customModes.map(mode => ({
        id: mode.slug, // 使用 slug 作为唯一标识
        name: mode.name,
        description: mode.description || mode.name,
        icon: getAnalystIcon(mode.slug),
        slug: mode.slug
      }))
      // 不再设置硬编码默认值，保持用户选择
      if (analysisForm.selectedAnalysts.length === 0) {
        analysisForm.selectedAnalysts = []
      }
    } else {
      analysts.value = []
      analysisForm.selectedAnalysts = []
    }
  } catch (error) {
    console.error('Failed to fetch analysts:', error)
    analysts.value = []
    analysisForm.selectedAnalysts = []
  } finally {
    loadingAnalysts.value = false
  }
}

// 分析步骤定义（动态生成）
const analysisSteps = ref<{ title: string; description: string; status: string }[]>([])

// 从后端步骤数据生成前端步骤
const generateStepsFromBackend = (backendSteps: { step?: string; name?: string; description?: string; status?: string }[]) => {
  if (!backendSteps || !Array.isArray(backendSteps)) {
    return []
  }

  return backendSteps.map((step: any, index: number) => ({
    key: `step_${index}`,
    title: step.name || `步骤 ${index + 1}`,
    description: step.description || '处理中...',
    status: 'pending'
  }))
}

// 模型设置
const modelSettings = ref({
  analystModel: 'qwen-turbo',
  debateModel: 'qwen-max'
})

// 可用的模型列表（从配置中获取）
const availableModels = ref<{ model_name: string; model_display_name?: string; capability_level?: number; suitable_roles?: string[]; provider?: string }[]>([])

// MCP工具列表
const mcpTools = ref<MCPTool[]>([])
const loadingMcpTools = ref(false)

// 🆕 模型推荐提示
// @ts-expect-error - reserved for future use
const _modelRecommendation = ref<{
  title: string
  message: string
  type: 'success' | 'warning' | 'info' | 'error'
  quickModel?: string
  deepModel?: string
} | null>(null)

// 分析表单
const analysisForm = reactive<AnalysisForm>({
  stockCode: '',  // 保留用于表单绑定
  symbol: '',     // 标准化后的代码
  market: 'A股',
  analysisDate: new Date(),
  selectedAnalysts: [], // 将在 onMounted 中加载默认值
  mcpTools: [],
  language: 'zh-CN',
  phases: {
    phase2: { enabled: false, debateRounds: 2 },
    phase3: { enabled: false, debateRounds: 1 },
    phase4: { enabled: true, debateRounds: 1 }
  }
})

// 辅助函数：安全获取阶段配置（避免模板中的类型索引问题）
const getPhaseConfig = (phaseName: string) => {
  return (analysisForm.phases as Record<string, { enabled: boolean; debateRounds: number }>)[phaseName]
}

// 归一化阶段配置：交易员始终执行，阶段2/3 可独立开关
const buildPhasePayload = (phases: any) => {
  const phase2Enabled = phases.phase2.enabled
  const phase3Enabled = phases.phase3.enabled
  // 交易员始终执行，phase4 始终为 true
  const phase4Enabled = true

  return {
    phase2_enabled: phase2Enabled,
    phase2_debate_rounds: phase2Enabled ? phases.phase2.debateRounds : 0,
    phase3_enabled: phase3Enabled,
    phase3_debate_rounds: phase3Enabled ? phases.phase3.debateRounds : 0,
    phase4_enabled: phase4Enabled,
    phase4_debate_rounds: 1 // Default to 1 round for Trader
  }
}

// 股票代码验证相关
const stockCodeError = ref<string>('')
const stockCodeHelp = ref<string>('')

// 估算总耗时
const estimatedTotalTime = computed(() => {
  return estimateTotalTime(analysisForm.phases)
})

// 禁用日期
const disabledDate = (time: Date) => {
  return time.getTime() > Date.now()
}

// 股票代码输入时的处理
const onStockCodeInput = () => {
  // 清除错误信息
  stockCodeError.value = ''
  // 显示格式提示
  stockCodeHelp.value = getStockCodeFormatHelp(analysisForm.market)
}

// 市场类型变更时的处理
const onMarketChange = () => {
  // 重新验证股票代码
  if (analysisForm.stockCode.trim()) {
    validateStockCodeInput()
  } else {
    // 显示新市场的格式提示
    stockCodeHelp.value = getStockCodeFormatHelp(analysisForm.market)
  }
}

// 获取股票信息
const fetchStockInfo = async () => {
  const code = analysisForm.stockCode.trim()
  if (!code) return

  try {
    const res = await stocksApi.getQuote(code)
    if (!res.success || !res.data) {
      if (import.meta.env.DEV) console.warn('股票信息获取失败:', res.message)
    }
  } catch (error) {
    console.error('获取股票信息失败:', (error as any)?.message || error)
  }
}

// 验证股票代码输入
const validateStockCodeInput = () => {
  const code = analysisForm.stockCode.trim()

  if (!code) {
    stockCodeError.value = ''
    stockCodeHelp.value = ''
    return
  }

  // 验证股票代码格式
  const validation = validateStockCode(code, analysisForm.market)

  if (!validation.valid) {
    stockCodeError.value = validation.message || '股票代码格式不正确'
    stockCodeHelp.value = ''
  } else {
    stockCodeError.value = ''
    stockCodeHelp.value = `✓ ${validation.market}代码格式正确`

    // 自动更新市场类型（如果识别出的市场与当前选择不同）
    if (validation.market && validation.market !== analysisForm.market) {
      analysisForm.market = validation.market
      ElMessage.success(`已自动识别为${validation.market}`)
    }

    // 标准化代码
    if (validation.normalizedCode) {
      analysisForm.stockCode = validation.normalizedCode
    }
  }

  // 获取股票信息
  fetchStockInfo()
}

// 解决图标组件
const resolveIcon = (name: string) => {
  const icons: Record<string, any> = {
    Document, TrendCharts, Histogram, ChatDotRound, DataAnalysis, Wallet, Money, Check, InfoFilled, WarningFilled, Loading
  }
  return icons[name] || InfoFilled
}

// 页面初始化
onMounted(async () => {
  await fetchAnalysts()
  initializeModelSettings()

  // 加载模型配置
  try {
    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.analystModel = defaultModels.analyst_model
    modelSettings.value.debateModel = defaultModels.debate_model

    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = (llmConfigs as any).filter((config: any) => config.enabled)
  } catch (error) {
    console.error('加载模型配置失败:', error)
  }

  // 加载MCP工具
  loadingMcpTools.value = true
  try {
    const res = await mcpApi.listTools()
    if (res.success && res.data) {
      mcpTools.value = res.data
    }
  } catch (error) {
    console.error('加载MCP工具失败:', error)
  } finally {
    loadingMcpTools.value = false
  }

  // 🆕 从用户偏好加载默认设置
  const authStore = useAuthStore()
  const appStore = useAppStore()

  // 优先从 authStore.user.preferences 读取，其次从 appStore.preferences 读取
  const userPrefs = authStore.user?.preferences
  if (userPrefs) {
    // 加载默认市场
    if (userPrefs.default_market) {
      analysisForm.market = userPrefs.default_market as MarketType
    }

    // 加载默认分析师（兼容旧的名称数据，统一规范化）
    if (userPrefs.default_analysts && userPrefs.default_analysts.length > 0) {
      analysisForm.selectedAnalysts = normalizeAnalystIds([...userPrefs.default_analysts])
    }
  } else {
    // 降级到 appStore.preferences
    if (appStore.preferences.defaultMarket) {
      analysisForm.market = appStore.preferences.defaultMarket as MarketType
    }
  }

  // 从用户偏好加载分析师选择 (如果有保存的偏好，且分析师列表已加载)
  if (authStore.user?.preferences?.default_analysts) {
    // 这里需要注意：用户偏好可能存的是旧的ID或名称，需要兼容
    // 简单起见，暂不覆盖 fetchAnalysts 中的默认逻辑，除非有明确映射
  }

  // 接收一次路由参数（从筛选页带入）- 路由参数优先级最高
  const q = route.query as any
  const hasNewStock = !!q?.stock
  if (hasNewStock) {
    analysisForm.stockCode = String(q.stock)
    // 🔥 关键修复：如果有新的股票代码，清除旧任务缓存
    clearTaskCache()
    console.log('🔄 检测到新股票代码，已清除旧任务缓存:', q.stock)

    // 🆕 自动识别市场类型（如果URL中没有明确指定market参数）
    if (!q?.market) {
      const detectedMarket = getMarketByStockCode(analysisForm.stockCode)
      analysisForm.market = detectedMarket as MarketType
    }
  }
  if (q?.market) analysisForm.market = normalizeMarketForAnalysis(q.market) as MarketType

  // 尝试恢复任务状态（仅当没有新股票代码时）
  if (!hasNewStock) {
    await restoreTaskFromCache()
  }
})

// 切换分析师
const toggleAnalyst = (analystId: string) => {
  const index = analysisForm.selectedAnalysts.indexOf(analystId)
  if (index > -1) {
    analysisForm.selectedAnalysts.splice(index, 1)
  } else {
    analysisForm.selectedAnalysts.push(analystId)
  }
}

// 提交分析
const submitAnalysis = async () => {
  const stockCode = analysisForm.stockCode.trim()
  if (!stockCode) {
    ElMessage.warning('请输入股票代码')
    return
  }

  // 验证股票代码格式
  const validation = validateStockCode(stockCode, analysisForm.market)
  if (!validation.valid) {
    ElMessage.error(validation.message || '股票代码格式不正确')
    stockCodeError.value = validation.message || '股票代码格式不正确'
    return
  }

  // 使用标准化后的代码
  analysisForm.symbol = validation.normalizedCode || stockCode.toUpperCase()

  if (analysisForm.selectedAnalysts.length === 0) {
    ElMessage.warning('请至少选择一个分析师')
    return
  }

  submitting.value = true

  try {
    // 确保 analysisDate 是 Date 对象
    const analysisDate = analysisForm.analysisDate instanceof Date
      ? analysisForm.analysisDate
      : new Date(analysisForm.analysisDate)

    const request: SingleAnalysisRequest = {
      symbol: analysisForm.symbol,
      stock_code: analysisForm.symbol,  // 兼容字段
      parameters: {
        market_type: analysisForm.market,
        analysis_date: analysisDate.toISOString().split('T')[0],
        selected_analysts: normalizeAnalystIds(analysisForm.selectedAnalysts), // 确保使用英文ID
        language: analysisForm.language,
        analyst_model: modelSettings.value.analystModel,
        debate_model: modelSettings.value.debateModel,
        // 阶段配置（按顺序依赖）
        ...buildPhasePayload(analysisForm.phases),
        // MCP工具
        mcp_tools: analysisForm.mcpTools
      }
    }

    const response = await analysisApi.startSingleAnalysis(request)

    ElMessage.success('分析任务已提交，正在处理中...')

    // 响应拦截器已返回 response.data，所以直接访问 response.data.task_id
    currentTaskId.value = response.data.task_id

    if (!currentTaskId.value) {
      console.error('[Analysis] startAnalysis: 任务ID为空')
      ElMessage.error('任务ID获取失败，请重试')
      return
    }

    // 保存任务状态到缓存
    saveTaskToCache(currentTaskId.value, {
      parameters: { ...analysisForm },
      submitTime: new Date().toISOString()
    })

    analysisStatus.value = 'running'
    showResults.value = false
    progressInfo.value = {
      progress: 0,
      currentStep: '正在初始化分析...',
      currentStepDescription: '分析任务已提交，正在启动分析流程',
      message: '分析任务已提交，正在启动分析流程',
      elapsedTime: 0,
      remainingTime: 0,
      totalTime: 0
    }

    // 初始化空的步骤列表，等待后端数据
    analysisSteps.value = []

    // 开始轮询任务状态
    startPollingTaskStatus()

    // 立即查询一次状态（不等待第一次轮询）
    initialQueryTimer = setTimeout(async () => {
      try {
        const response = await analysisApi.getTaskStatus(currentTaskId.value)
        const status = response.data // 响应拦截器已返回 response.data
        if (status.status === 'running') {
          analysisStatus.value = 'running'
          updateProgressInfo(status)
        }
      } catch (error) {
        console.error('[Analysis] 立即查询状态失败:', error)
      }
    }, 1000) // 1秒后查询

  } catch (error: any) {
    ElMessage.error(error.message || '提交分析失败')
  } finally {
    submitting.value = false
  }
}

// 轮询任务状态
const startPollingTaskStatus = () => {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
  }

  // 检查任务ID是否有效
  if (!currentTaskId.value) {
    console.error('[Analysis] startPolling: 任务ID为空')
    return
  }

  pollingTimer.value = setInterval(async () => {
    try {
      if (!currentTaskId.value) {
        if (pollingTimer.value) {
          clearInterval(pollingTimer.value)
        }
        return
      }

      const response = await analysisApi.getTaskStatus(currentTaskId.value)
      const status = response.data // 响应拦截器已返回 response.data

      if (status.status === 'completed') {
        // 分析完成，调用专门的结果API获取完整数据

        try {
          const resultData = await analysisApi.getTaskResult(currentTaskId.value)
          // resultData 是 ApiResponse: { success, data, message }
          if (resultData && resultData.success) {
            analysisResults.value = resultData.data
          } else {
            // 回退到状态中的数据
            console.error('[Analysis] 获取分析结果失败:', resultData?.message)
            analysisResults.value = status.result_data
          }
        } catch (error) {
          // 回退到状态中的数据
          console.error('[Analysis] 获取分析结果异常:', error)
          analysisResults.value = status.result_data
        }

        analysisStatus.value = 'completed'
        showResults.value = true
        progressInfo.value.progress = 100
        progressInfo.value.currentStep = '分析完成'
        progressInfo.value.message = '分析已完成！'

        if (pollingTimer.value) {
          clearInterval(pollingTimer.value)
          pollingTimer.value = null
        }

        // 任务完成后保持缓存，以便刷新后能看到结果
        // clearTaskCache() // 不清除，让用户能在30分钟内刷新查看结果

        ElMessage.success('分析完成！')

      } else if (status.status === 'failed') {
        // 分析失败
        analysisStatus.value = 'failed'
        progressInfo.value.currentStep = '分析失败'

        // 格式化错误消息（保留换行符）
        const errorMessage = status.error_message || '分析过程中发生错误'
        progressInfo.value.message = errorMessage

        if (pollingTimer.value) {
          clearInterval(pollingTimer.value)
          pollingTimer.value = null
        }

        // 任务失败时清除缓存
        clearTaskCache()

        // 显示友好的错误提示（使用 dangerouslyUseHTMLString 支持换行）
        ElMessage({
          type: 'error',
          message: errorMessage.replace(/\n/g, '<br>'),
          dangerouslyUseHTMLString: true,
          duration: 10000, // 显示10秒，让用户有时间阅读
          showClose: true
        })

      } else if (status.status === 'running' || status.status === 'processing' || status.status === 'pending' || status.status === undefined) {
        // 分析进行中（含 pending/processing 兜底），更新进度
        console.log('🔄 轮询中设置 analysisStatus 为 running')
        analysisStatus.value = 'running'
        updateProgressInfo(status)
      }

    } catch (error) {
      console.error('获取任务状态失败:', error)
      // 继续轮询，不中断
    }
  }, 5000) // 每5秒轮询一次
}

// 更新进度信息
const updateProgressInfo = (status: any) => {
  if (import.meta.env.DEV) {
    console.log('🔄 更新进度信息:', { status: status?.status, progress: status?.progress_percentage })
  }

  // 使用后端返回的实际进度数据（兼容 progress_percentage）
  const progressValue = status.progress_percentage ?? status.progress
  if (progressValue !== undefined) {
    console.log('📊 更新进度:', progressValue)
    progressInfo.value.progress = Number(progressValue) || 0
  }

  const currentStep =
    status.current_step_name ||
    status.current_step ||
    status.current_step_display ||
    ''
  if (currentStep) {
    console.log('📋 更新步骤:', currentStep)
    progressInfo.value.currentStep = currentStep
  }

  const stepDescription =
    status.current_step_description ||
    status.message ||
    status.current_step_detail ||
    ''
  if (stepDescription) {
    console.log('📝 更新步骤描述:', stepDescription)
    progressInfo.value.currentStepDescription = stepDescription
  }

  if (status.message) {
    progressInfo.value.message = status.message
  }

  // 接收后端返回的时间数据
  if (status.elapsed_time !== undefined) {
    progressInfo.value.elapsedTime = status.elapsed_time
  }

  if (status.remaining_time !== undefined) {
    progressInfo.value.remainingTime = status.remaining_time
  }

  if (status.estimated_total_time !== undefined) {
    progressInfo.value.totalTime = status.estimated_total_time
  }

  // 如果后端提供了步骤数据，更新步骤列表
  if (status.steps && Array.isArray(status.steps)) {
    if (analysisSteps.value.length === 0) {
      // 首次生成步骤列表
      analysisSteps.value = generateStepsFromBackend(status.steps)
      console.log('📋 从后端生成步骤列表:', analysisSteps.value.length, '个步骤')
    }
  }

  console.log('🔄 更新后进度信息:', progressInfo.value)

  // 更新分析步骤状态
  updateAnalysisSteps(status)

  // 前端不进行估算，只展示后端返回的数据
  progressInfo.value.message = status.message || '分析正在进行中...'
}

// 重新开始分析
const restartAnalysis = () => {
  // 清除任务缓存
  clearTaskCache()

  analysisStatus.value = 'idle'
  showResults.value = false
  analysisResults.value = null
  currentTaskId.value = ''
  progressInfo.value = {
    progress: 0,
    currentStep: '',
    currentStepDescription: '',
    message: '',
    elapsedTime: 0,
    remainingTime: 0,
    totalTime: 0
  }

  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}


// 获取操作标签类型
const getActionTagType = (action: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  const actionTypes: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    '买入': 'success',
    '持有': 'warning',
    '卖出': 'danger',
    '观望': 'info'
  }
  return actionTypes[action] || 'info'
}

// 格式化百分比显示，处理 null/undefined/NaN 情况
const formatPercentage = (value: number | null | undefined): string => {
  if (value === null || value === undefined || isNaN(value)) {
    return '暂无'
  }
  return `${(value * 100).toFixed(1)}%`
}

// 获取分析报告
const getAnalysisReports = (data: any) => {
  console.log('📊 getAnalysisReports 输入数据:', data)
  const reports: Array<{title: string, content: any}> = []

  // 优先从 reports 字段获取数据（新的API格式）
  let reportsData = data
  if (data && data.reports && typeof data.reports === 'object') {
    reportsData = data.reports
    console.log('📊 使用 data.reports:', reportsData)
  } else if (data && data.state && typeof data.state === 'object') {
    reportsData = data.state
    console.log('📊 使用 data.state:', reportsData)
  } else {
    if (import.meta.env.DEV) console.log('没有找到有效的报告数据')
    return reports
  }

  // 非第1阶段的固定报告映射（研究团队、交易团队、风险管理团队等）
  const fixedReportMappings: Record<string, { title: string, category: string }> = {
    // 研究团队 (3个)
    'bull_researcher': { title: '🐂 多头研究员', category: '研究团队' },
    'bear_researcher': { title: '🐻 空头研究员', category: '研究团队' },
    'research_team_decision': { title: '🔬 研究经理决策', category: '研究团队' },

    // 交易团队 (1个)
    'trader_investment_plan': { title: '💼 交易员计划', category: '交易团队' },

    // 风险管理团队 (4个)
    'risky_analyst': { title: '⚡ 激进分析师', category: '风险管理团队' },
    'safe_analyst': { title: '🛡️ 保守分析师', category: '风险管理团队' },
    'neutral_analyst': { title: '⚖️ 中性分析师', category: '风险管理团队' },
    'risk_management_decision': { title: '👔 投资组合经理', category: '风险管理团队' },

    // 最终决策 (1个)
    'final_trade_decision': { title: '🎯 最终交易决策', category: '最终决策' },

    // 兼容旧格式 - 投资建议保留，其他内部状态隐藏
    'investment_plan': { title: '📋 投资建议', category: '其他' }
  }

  // 从已加载的分析师列表动态生成第1阶段报告映射
  const dynamicReportMappings: Record<string, { title: string, category: string }> = {}
  analysts.value.forEach(analyst => {
    const internalKey = analyst.slug.replace('-analyst', '').replace(/-/g, '_')
    const reportKey = `${internalKey}_report`
    dynamicReportMappings[reportKey] = {
      title: `📊 ${analyst.name}`,
      category: '分析师团队'
    }
  })

  // 合并映射（动态映射优先）
  const allMappings = { ...dynamicReportMappings, ...fixedReportMappings }

  // 已处理的报告键集合
  const processedKeys = new Set<string>()

  // 先处理已知映射的报告
  Object.entries(allMappings).forEach(([key, mapping]) => {
    const content = reportsData[key]
    if (content) {
      if (import.meta.env.DEV) console.log(`找到报告: ${key} -> ${mapping.title}`)
      reports.push({
        title: mapping.title,
        content: content
      })
      processedKeys.add(key)
    }
  })

  // 动态发现所有以 _report 结尾的报告（处理未在映射中的新报告）
  Object.keys(reportsData).forEach(key => {
    if (key.endsWith('_report') && !processedKeys.has(key) && reportsData[key]) {
      // 自动生成标题：将下划线替换为空格，移除 _report 后缀
      const autoTitle = `📊 ${key.replace('_report', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}`
      if (import.meta.env.DEV) console.log(`动态发现报告: ${key} -> ${autoTitle}`)
      reports.push({
        title: autoTitle,
        content: reportsData[key]
      })
    }
  })

  if (import.meta.env.DEV) console.log(`总共找到 ${reports.length} 个报告`)

  // 设置第一个报告为默认激活标签页
  if (reports.length > 0 && !activeReportTab.value) {
    activeReportTab.value = '0'
  }

  return reports
}

// 获取报告图标
const getReportIcon = (title: string) => {
  const iconMap: Record<string, string> = {
    '📈 市场技术分析': '📈',
    '💰 基本面分析': '💰',
    '📰 新闻事件分析': '📰',
    '💭 市场情绪分析': '💭',
    '📋 投资建议': '📋',
    '🔬 研究团队决策': '🔬',
    '💼 交易团队计划': '💼',
    '⚖️ 风险管理团队': '⚖️',
    '🎯 最终交易决策': '🎯'
  }
  return iconMap[title] || '📊'
}

// 获取报告名称（去掉图标）
const getReportName = (title: string) => {
  return title.replace(/^[^\s]+\s/, '')
}

// 获取报告描述
const getReportDescription = (title: string) => {
  const descMap: Record<string, string> = {
    '📈 市场技术分析': '技术指标、价格趋势、支撑阻力位分析',
    '💰 基本面分析': '财务数据、估值水平、盈利能力分析',
    '📰 新闻事件分析': '相关新闻事件、市场动态影响分析',
    '💭 市场情绪分析': '投资者情绪、社交媒体情绪指标',
    '📋 投资建议': '具体投资策略、仓位管理建议',
    '🔬 研究团队决策': '多头/空头研究员辩论分析，研究经理综合决策',
    '💼 交易团队计划': '专业交易员制定的具体交易执行计划',
    '⚖️ 风险管理团队': '激进/保守/中性分析师风险评估，投资组合经理最终决策',
    '🎯 最终交易决策': '综合所有团队分析后的最终投资决策'
  }
  return descMap[title] || '详细分析报告'
}

// 格式化报告内容
const formatReportContent = (content: any) => {
  if (!content) {
    return ''
  }

  // 如果content不是字符串，转换为字符串
  let stringContent = ''
  if (typeof content === 'string') {
    stringContent = content
  } else if (typeof content === 'object') {
    if (content.judge_decision) {
      stringContent = content.judge_decision
    } else {
      stringContent = JSON.stringify(content, null, 2)
    }
  } else {
    stringContent = String(content)
  }

  try {
    // 使用 renderMarkdown 安全地将 Markdown 转换为经过 DOMPurify 消毒的 HTML
    return renderMarkdown(stringContent)
  } catch (error) {
    console.error('Markdown渲染失败:', (error as any)?.message || error)
    // 如果渲染失败，回退到简单的文本显示
    const escaped = stringContent.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${escaped}</pre>`
  }
}

// 下载报告
const downloadReport = async (format: string = 'markdown') => {
  try {
    if (!analysisResults.value && !currentTaskId.value) {
      ElMessage.error('报告尚未生成，无法下载')
      return
    }

    // 显示加载提示
    const loadingMsg = ElMessage({
      message: `正在生成${getFormatName(format)}格式报告...`,
      type: 'info',
      duration: 0
    })

    const reportId = (analysisResults.value?.id as any) || currentTaskId.value
    const blob = await reportsApi.download(reportId, format)

    loadingMsg.close()

    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const code =
      analysisResults.value?.stock_code ||
      analysisResults.value?.stock_symbol ||
      analysisResults.value?.symbol ||
      'stock'
    const dateStr = analysisResults.value?.analysis_date || new Date().toISOString().slice(0, 10)

    // 根据格式设置文件扩展名
    const ext = getFileExtension(format)
    a.download = `${String(code)}_分析报告_${String(dateStr).slice(0, 10)}.${ext}`

    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)

    ElMessage.success(`${getFormatName(format)}报告下载成功`)
  } catch (err: any) {
    console.error('下载报告出错:', err)

    // 显示详细错误信息
    if (err.message && err.message.includes('pandoc')) {
      ElMessage.error({
        message: 'PDF/Word 导出需要安装 pandoc 工具',
        duration: 5000
      })
    } else {
      ElMessage.error(`下载报告失败: ${err.message || '未知错误'}`)
    }
  }
}

// 辅助函数：获取格式名称
const getFormatName = (format: string): string => {
  const names: Record<string, string> = {
    'markdown': 'Markdown',
    'docx': 'Word',
    'pdf': 'PDF',
    'json': 'JSON'
  }
  return names[format] || format
}

// 辅助函数：获取文件扩展名
const getFileExtension = (format: string): string => {
  const extensions: Record<string, string> = {
    'markdown': 'md',
    'docx': 'docx',
    'pdf': 'pdf',
    'json': 'json'
  }
  return extensions[format] || 'txt'
}

// 组件销毁时清理定时器和事件监听
onUnmounted(() => {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
  if (initialQueryTimer) {
    clearTimeout(initialQueryTimer)
    initialQueryTimer = null
  }
  if (visibilityRefreshTimer) {
    clearTimeout(visibilityRefreshTimer)
    visibilityRefreshTimer = null
  }
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

// 页面可见性变化时的处理
let visibilityRefreshTimer: ReturnType<typeof setTimeout> | null = null
const handleVisibilityChange = () => {
  if (document.hidden) {
    // 页面隐藏时清理延迟定时器
    if (visibilityRefreshTimer) {
      clearTimeout(visibilityRefreshTimer)
      visibilityRefreshTimer = null
    }
  } else {
    // 页面重新可见时，延迟查询一次状态
    if (currentTaskId.value && analysisStatus.value === 'running') {
      visibilityRefreshTimer = setTimeout(async () => {
        visibilityRefreshTimer = null
        try {
          const response = await analysisApi.getTaskStatus(currentTaskId.value)
          const status = response.data
          if (status.status === 'running') {
            analysisStatus.value = 'running'
            updateProgressInfo(status)
          }
        } catch (error) {
          console.error('页面恢复查询状态失败:', error)
        }
      }, 500)
    }
  }
}

// 监听页面可见性变化
document.addEventListener('visibilitychange', handleVisibilityChange)

// 获取进度条状态
const getProgressStatus = () => {
  if (analysisStatus.value === 'completed') {
    return 'success'
  } else if (analysisStatus.value === 'failed') {
    return 'exception'
  } else if (analysisStatus.value === 'running') {
    return '' // 默认状态，显示蓝色进度条
  }
  return ''
}

// 简单的时间格式化方法（只用于显示后端返回的时间）
const formatTime = (seconds: number) => {
  if (!seconds || seconds <= 0) {
    return '计算中...'
  }

  if (seconds < 60) {
    return `${Math.floor(seconds)}秒`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.floor(seconds % 60)
    return remainingSeconds > 0 ? `${minutes}分${remainingSeconds}秒` : `${minutes}分钟`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}小时${minutes}分钟`
  }
}

// 更新分析步骤状态
const updateAnalysisSteps = (status: any) => {
  if (analysisSteps.value.length === 0) {
    if (import.meta.env.DEV) console.log('📋 没有步骤定义，跳过更新')
    return
  }

  // 优先使用后端提供的详细步骤信息
  let currentStepIndex = 0

  if (typeof status.current_step === 'number') {
    // 后端提供了精确的步骤索引（仅当为数字时使用）
    currentStepIndex = status.current_step
    console.log('📋 使用后端步骤索引:', currentStepIndex)
  } else {
    // 兜底方案：使用进度百分比估算
    const progress = status.progress_percentage ?? status.progress ?? 0
    if (progress > 0) {
      const progressRatio = progress / 100
      currentStepIndex = Math.floor(progressRatio * (analysisSteps.value.length - 1))
      if (progress > 0 && currentStepIndex === 0) {
        currentStepIndex = 1
      }
    }
    console.log('📋 使用进度估算步骤索引:', currentStepIndex, '进度:', progress)
  }

  // 确保索引在有效范围内
  currentStepIndex = Math.max(0, Math.min(currentStepIndex, analysisSteps.value.length - 1))

  console.log('📋 最终步骤索引:', currentStepIndex, '/', analysisSteps.value.length)

  // 更新所有步骤状态
  analysisSteps.value.forEach((step, index) => {
    if (index < currentStepIndex) {
      step.status = 'completed'
    } else if (index === currentStepIndex) {
      step.status = 'current'
    } else {
      step.status = 'pending'
    }
  })

  const statusSummary = analysisSteps.value.map((s, i) => `${i}:${s.status}`).join(', ')
  if (import.meta.env.DEV) console.log('📋 步骤状态更新完成:', statusSummary)
}

// 初始化模型设置
const initializeModelSettings = async () => {
  try {
    // 获取默认模型
    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.analystModel = defaultModels.analyst_model
    modelSettings.value.debateModel = defaultModels.debate_model

    // 获取所有可用的模型列表
    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = (llmConfigs as any).filter((config: any) => config.enabled)

    if (import.meta.env.DEV) {
      console.log('加载模型配置成功:', {
        quick: modelSettings.value.analystModel,
        deep: modelSettings.value.debateModel,
        available: availableModels.value.length
      })
    }
  } catch (error) {
    console.error('加载默认模型配置失败:', (error as any)?.message || error)
    modelSettings.value.analystModel = 'qwen-turbo'
    modelSettings.value.debateModel = 'qwen-max'
  }
}

// 任务状态缓存管理
const TASK_CACHE_KEY = 'trading_analysis_task'
const TASK_CACHE_DURATION = 30 * 60 * 1000 // 30分钟

// 保存任务状态到缓存
const saveTaskToCache = (taskId: string, taskData: any) => {
  const cacheData = {
    taskId,
    taskData,
    timestamp: Date.now()
  }
  localStorage.setItem(TASK_CACHE_KEY, JSON.stringify(cacheData))
  console.log('💾 任务状态已缓存:', taskId)
}

// 从缓存获取任务状态
const getTaskFromCache = () => {
  try {
    const cached = localStorage.getItem(TASK_CACHE_KEY)
    if (!cached) return null

    const cacheData = JSON.parse(cached)
    const now = Date.now()

    // 检查是否过期（30分钟）
    if (now - cacheData.timestamp > TASK_CACHE_DURATION) {
      localStorage.removeItem(TASK_CACHE_KEY)
      console.log('🗑️ 缓存已过期，已清理')
      return null
    }

    console.log('📦 从缓存恢复任务:', cacheData.taskId)
    return cacheData
  } catch (error) {
    console.error('❌ 读取缓存失败:', error)
    localStorage.removeItem(TASK_CACHE_KEY)
    return null
  }
}

// 清除任务缓存
const clearTaskCache = () => {
  localStorage.removeItem(TASK_CACHE_KEY)
  console.log('🗑️ 任务缓存已清除')
}

// 恢复任务状态
const restoreTaskFromCache = async () => {
  const cached = getTaskFromCache()
  if (!cached) return false

  try {
    console.log('🔄 尝试恢复任务状态:', cached.taskId)

    // 查询任务当前状态
    const response = await analysisApi.getTaskStatus(cached.taskId)
    const status = response.data // 响应拦截器已返回 response.data

    if (import.meta.env.DEV) {
      console.log('📊 恢复的任务状态:', { status: status?.status, task_id: cached.taskId })
    }

    if (status.status === 'completed') {
      // 任务已完成，显示结果
      currentTaskId.value = cached.taskId
      analysisStatus.value = 'completed'
      showResults.value = true
      analysisResults.value = status.result_data
      progressInfo.value.progress = 100
      progressInfo.value.currentStep = '分析完成'
      progressInfo.value.message = '分析已完成'

      // 恢复分析参数
      if (cached.taskData.parameters) {
        Object.assign(analysisForm, cached.taskData.parameters)
      }

      console.log('✅ 任务已完成，显示结果')
      return true

    } else if (status.status === 'running') {
      // 任务仍在运行，恢复进度显示
      currentTaskId.value = cached.taskId
      analysisStatus.value = 'running'
      showResults.value = false
      updateProgressInfo(status)

      // 恢复分析参数
      if (cached.taskData.parameters) {
        Object.assign(analysisForm, cached.taskData.parameters)
      }

      // 启动轮询
      startPollingTaskStatus()

      console.log('🔄 任务仍在运行，恢复进度显示')
      return true

    } else if (status.status === 'failed') {
      // 任务失败
      analysisStatus.value = 'failed'
      progressInfo.value.currentStep = '分析失败'
      progressInfo.value.message = status.error_message || '分析过程中发生错误'

      // 清除缓存
      clearTaskCache()

      console.log('❌ 任务失败')
      return true

    } else {
      // 其他状态，清除缓存
      clearTaskCache()
      console.log('🤔 未知任务状态，清除缓存')
      return false
    }

  } catch (error) {
    console.error('❌ 恢复任务状态失败:', error)
    // 如果查询失败，可能是任务不存在了，清除缓存
    clearTaskCache()
    return false
  }
}

// 🆕 模型能力相关辅助函数

/**
 * 获取能力等级文本
 */
const getCapabilityText = (level: number): string => {
  const texts: Record<number, string> = {
    1: '⚡基础',
    2: '📊标准',
    3: '🎯高级',
    4: '🔥专业',
    5: '👑旗舰'
  }
  return texts[level] || '📊标准'
}

/**
 * 获取能力等级标签类型
 */
const getCapabilityTagType = (level: number): 'success' | 'info' | 'warning' | 'danger' => {
  if (level >= 4) return 'danger'
  if (level >= 3) return 'warning'
  if (level >= 2) return 'success'
  return 'info'
}

/**
 * 判断是否适合快速分析
 */
const isAnalystRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('analyst') || roles.includes('both')
}

// 监听分析深度变化
import { watch } from 'vue'

// 阶段开关已独立：Phase 2（辩论）和 Phase 3（风险辩论）可分别开关，交易员始终执行

// 监听模型选择变化
watch([() => modelSettings.value.analystModel, () => modelSettings.value.debateModel], () => {
  // checkModelSuitability() // Removed
})
</script>

<style lang="scss" scoped>
.single-analysis {
  min-height: 100vh;
  background: var(--el-bg-color-page);
  padding: 24px;

  .page-header {
    margin-bottom: 32px;

    .header-content {
      background: var(--el-bg-color);
      padding: 32px;
      border-radius: 16px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    }

    .title-section {
      .page-title {
        display: flex;
        align-items: center;
        font-size: 32px;
        font-weight: 700;
        color: var(--el-text-color-primary);
        margin: 0 0 8px 0;

        .title-icon {
          margin-right: 12px;
          color: var(--el-color-primary);
        }
      }

      .page-description {
        font-size: 16px;
        color: #64748b;
        margin: 0;
      }
    }
  }

  .analysis-container {
    .main-form-card, .config-card {
      border-radius: 16px;
      border: none;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);

      :deep(.el-card__header) {
        background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%);
        color: white;
        border-radius: 16px 16px 0 0;
        padding: 20px 24px;

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;

          h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
          }
        }
      }

      :deep(.el-card__body) {
        padding: 24px;
      }
    }

    .analysis-form {
      .form-section {
        margin-bottom: 32px;
        width: 100%;
        display: flex;
        flex-direction: column;

        .section-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin: 0 0 16px 0;
          padding-bottom: 8px;
          border-bottom: 2px solid #e2e8f0;
        }
      }

      .stock-input {
        :deep(.el-input__inner) {
          font-weight: 600;
          text-transform: uppercase;
        }

        &.is-error {
          :deep(.el-input__inner) {
            border-color: #E57373;
          }
        }
      }

      .error-message {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        font-size: 12px;
        color: #E57373;

        .el-icon {
          font-size: 14px;
        }
      }

      .help-message {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        font-size: 12px;
        color: #7CB342;

        .el-icon {
          font-size: 14px;
        }
      }

      .prompt-helper {
        margin-top: 8px;
        color: #94a3b8;
        font-size: 12px;
      }

      .analysts-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 16px;

        .analyst-card {
          display: flex;
          align-items: center;
          padding: 16px;
          border: 2px solid #e2e8f0;
          border-radius: 12px;
          cursor: pointer;
          transition: all 0.3s ease;

          &:hover {
            border-color: var(--el-color-primary);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(197, 165, 90, 0.15);
          }

          &.active {
            border-color: var(--el-color-primary);
            background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, #f5edd6 100%);
            color: #7a6530;
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(197, 165, 90, 0.15);
          }

          &.disabled {
            opacity: 0.5;
            cursor: not-allowed;

            &:hover {
              transform: none;
              box-shadow: none;
              border-color: #e2e8f0;
            }
          }

          .analyst-avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 16px;
            font-size: 20px;
          }

          .analyst-content {
            flex: 1;

            .analyst-name {
              font-weight: 600;
              margin-bottom: 4px;
            }

            .analyst-desc {
              font-size: 12px;
              opacity: 0.8;
            }
          }

          .analyst-check {
            .check-icon {
              font-size: 20px;
              color: var(--el-color-primary);
            }
          }

          &.active .analyst-check .check-icon {
            color: #7a6530;
          }
        }
      }
    }

    .config-card {
      .config-content {
        .config-section {
          margin-bottom: 24px;

          .config-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--el-text-color-primary);
            margin: 0 0 12px 0;
            display: flex;
            align-items: center;
            gap: 8px;
          }

          .model-config {
            .model-item {
              margin-bottom: 16px;

              .model-label {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
                font-size: 13px;
                color: #374151;

                .help-icon {
                  color: #9ca3af;
                  cursor: help;
                }
              }
            }
          }

          .option-list {
            .option-item {
              display: flex;
              align-items: center;
              justify-content: space-between;
              padding: 12px 0;
              border-bottom: 1px solid #f3f4f6;

              &:last-child {
                border-bottom: none;
              }

              .option-info {
                .option-name {
                  font-size: 14px;
                  font-weight: 500;
                  color: #374151;
                  display: block;
                  margin-bottom: 2px;
                }

                .option-desc {
                  font-size: 12px;
                  color: #6b7280;
                }
              }
            }
          }

          .custom-input {
            :deep(.el-textarea__inner) {
              border-radius: 8px;
              border: 1px solid #d1d5db;

              &:focus {
                border-color: #C5A55A;
                box-shadow: 0 0 0 3px rgba(197, 165, 90, 0.1);
              }
            }
          }

          .input-help {
            font-size: 12px;
            color: #6b7280;
            margin-top: 8px;
          }

          .action-buttons {
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            margin-top: 24px !important;
            width: 100% !important;
            text-align: center !important;

            .submit-btn.el-button {
              width: 280px !important;
              height: 56px !important;
              font-size: 18px !important;
              font-weight: 700 !important;
              background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
              border: none !important;
              border-radius: 16px !important;
              transition: all 0.3s ease !important;
              box-shadow: 0 4px 15px rgba(197, 165, 90, 0.2) !important;
              min-width: 280px !important;
              max-width: 280px !important;

              &:hover {
                transform: translateY(-3px) !important;
                box-shadow: 0 12px 30px rgba(197, 165, 90, 0.4) !important;
                background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
              }

              &:disabled {
                opacity: 0.6 !important;
                transform: none !important;
                box-shadow: 0 4px 15px rgba(197, 165, 90, 0.1) !important;
              }

              .el-icon {
                margin-right: 8px !important;
                font-size: 20px !important;
              }

              span {
                font-size: 18px !important;
                font-weight: 700 !important;
              }
            }
          }
        }
      }
    }

    .action-section {
      margin-top: 24px;
      display: flex;
      gap: 16px;

      .submit-btn {
        flex: 1;
        height: 48px;
        font-size: 16px;
        font-weight: 600;
        background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%);
        border: none;
        border-radius: 12px;
        transition: all 0.3s ease;

        &:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 25px rgba(197, 165, 90, 0.3);
        }

        &:disabled {
          opacity: 0.6;
          transform: none;
          box-shadow: none;
        }
      }

      .reset-btn {
        height: 48px;
        font-size: 16px;
        border-radius: 12px;
        border: 2px solid #e5e7eb;
        color: #6b7280;
        transition: all 0.3s ease;

        &:hover {
          border-color: #d1d5db;
          color: #374151;
          transform: translateY(-1px);
        }
      }
    }
  }
}

/* 阶段配置样式 */
.phases-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;

  .phase-card {
    border: 2px solid #e2e8f0;
    border-radius: 12px;
    padding: 16px;
    transition: all 0.3s ease;
    background: #f8fafc;

    &:hover {
      border-color: #cbd5e1;
      transform: translateY(-2px);
    }

    &.enabled {
      background: #fff;
      border-color: #C5A55A;
      box-shadow: 0 4px 12px rgba(197, 165, 90, 0.1);

      .phase-header .phase-title {
        color: #C5A55A;
      }
    }

    .phase-header {
      margin-bottom: 12px;

      .phase-title-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;

        .phase-title {
          font-weight: 600;
          font-size: 15px;
          color: var(--el-text-color-primary);
        }
      }

      .phase-desc {
        font-size: 12px;
        color: #64748b;
        line-height: 1.5;
        min-height: 36px;
      }
    }

    .phase-body {
      padding-top: 12px;
      border-top: 1px solid #e2e8f0;
      animation: fadeIn 0.3s ease;

      .phase-agents {
        margin-bottom: 12px;

        .label {
          font-size: 12px;
          color: #64748b;
          margin-bottom: 6px;
          display: block;
        }

        .agent-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
      }

      .phase-rounds {
        display: flex;
        justify-content: space-between;
        align-items: center;

        .label {
          font-size: 12px;
          color: #64748b;
        }
      }
    }
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}

// 分析步骤样式
.step-item {
  display: flex;
  align-items: flex-start;
  padding: 12px 0;
  border-left: 3px solid #e5e7eb;
  margin-left: 15px;
  position: relative;
  transition: all 0.3s ease;

  &.step-completed {
    border-left-color: #10b981;

    .step-icon {
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: white;
      box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
    }

    .step-title {
      color: #10b981;
      font-weight: 600;
    }

    .step-description {
      color: #059669;
    }
  }

  &.step-current {
    border-left-color: #C5A55A;
    background: linear-gradient(90deg, rgba(197, 165, 90, 0.05) 0%, transparent 100%);

    .step-icon {
      background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%);
      color: white;
      box-shadow: 0 2px 12px rgba(197, 165, 90, 0.4);
    }

    .step-title {
      color: #C5A55A;
      font-weight: 700;
    }

    .step-description {
      color: #9E7E3E;
      font-weight: 500;
    }
  }

  &.step-pending {
    .step-icon {
      background: #f3f4f6;
      color: #9ca3af;
      border: 2px solid #e5e7eb;
    }

    .step-title {
      color: #6b7280;
    }

    .step-description {
      color: #9ca3af;
    }
  }
}

.step-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: -16px;
  margin-right: 16px;
  font-size: 14px;
  flex-shrink: 0;
  z-index: 1;
  transition: all 0.3s ease;
}

.completed-icon {
  color: white;
}

.current-icon {
  color: white;
}

.pending-icon {
  color: #9ca3af;
}

.step-content {
  flex: 1;
  min-width: 0;
  padding-right: 16px;
}

.step-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
  line-height: 1.4;
}

.step-description {
  font-size: 12px;
  line-height: 1.4;
  opacity: 0.9;
}

/* 脉冲动画 */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.05);
  }
}

/* 为当前步骤图标添加脉冲效果 */
.step-current .step-icon {
  animation: pulse 2s ease-in-out infinite;
}
</style>

<style>
/* 全局样式确保按钮样式生效 */
.action-buttons {
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  width: 100% !important;
  text-align: center !important;
}

.large-analysis-btn.el-button {
  width: 280px !important;
  height: 56px !important;
  font-size: 18px !important;
  font-weight: 700 !important;
  background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
  border: none !important;
  border-radius: 16px !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 4px 15px rgba(197, 165, 90, 0.2) !important;
  min-width: 280px !important;
  max-width: 280px !important;
}

.large-analysis-btn.el-button:hover {
  transform: translateY(-3px) !important;
  box-shadow: 0 12px 30px rgba(197, 165, 90, 0.4) !important;
  background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
}

.large-analysis-btn.el-button:disabled {
  opacity: 0.6 !important;
  transform: none !important;
  box-shadow: 0 4px 15px rgba(197, 165, 90, 0.1) !important;
}

.large-analysis-btn.el-button .el-icon {
  margin-right: 8px !important;
  font-size: 20px !important;
}

.large-analysis-btn.el-button span {
  font-size: 18px !important;
  font-weight: 700 !important;
}

/* 进度显示样式 */
.progress-section {
  margin-top: 24px;
}

.progress-card .progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-card .progress-header h4 {
  margin: 0;
  color: #1f2937;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 旋转动画 */
.rotating-icon {
  animation: rotate 2s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 总体进度信息 */
.overall-progress-info {
  margin-bottom: 24px;
}

.progress-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stat-item {
  text-align: center;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  border: 1px solid var(--el-border-color);
}

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  font-weight: 500;
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

/* 进度条区域 */
.progress-bar-section {
  margin-bottom: 24px;
}

.main-progress-bar {
  :deep(.el-progress-bar__outer) {
    background-color: var(--el-fill-color);
    border-radius: 8px;
  }

  :deep(.el-progress-bar__inner) {
    background: linear-gradient(90deg, #C5A55A 0%, #9E7E3E 100%);
    border-radius: 8px;
    transition: width 0.6s ease;
  }

  :deep(.el-progress__text) {
    font-weight: 600;
    color: var(--el-text-color-primary);
  }
}

/* 当前任务信息 */
.current-task-info {
  background: var(--el-fill-color-light);
  border: 1px solid #C5A55A;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 24px;
}

.task-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #9E7E3E;
  margin-bottom: 8px;
}

.task-icon {
  color: #C5A55A;
}

.task-description {
  font-size: 14px;
  color: #9E7E3E;
  line-height: 1.5;
}

/* 分析步骤 */
.analysis-steps {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
}

.steps-title {
  margin: 0 0 16px 0;
  color: #1e293b;
  font-size: 16px;
  font-weight: 600;
}

.steps-container {
  max-height: 300px;
  overflow-y: auto;
}

/* 结果显示样式 */
.results-section {
  margin-top: 24px;
}

.results-card .results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.results-card .results-header h3 {
  margin: 0;
  color: #1f2937;
}

.results-card .result-meta {
  display: flex;
  gap: 8px;
}

/* 风险提示样式 */
.risk-disclaimer {
  margin-bottom: 24px;
  animation: fadeInDown 0.5s ease-out;
}

.risk-disclaimer :deep(.el-alert) {
  background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%);
  border: 2px solid #ffc107;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
}

.risk-disclaimer :deep(.el-alert__icon) {
  font-size: 24px;
  color: #ff6b00;
}

.disclaimer-content {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  line-height: 1.6;
}

.disclaimer-icon {
  font-size: 24px;
  color: #ff6b00;
  flex-shrink: 0;
  animation: pulse 2s ease-in-out infinite;
}

.disclaimer-text {
  color: #856404;
  flex: 1;
}

.disclaimer-text strong {
  color: #d63031;
  font-size: 16px;
  font-weight: 700;
}

@keyframes pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.8;
  }
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.decision-section {
  margin-bottom: 32px;
}

.decision-section h4 {
  color: #1f2937;
  margin-bottom: 16px;
}

.decision-card {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
}

.decision-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}

.decision-action {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.decision-action .label {
  font-weight: 600;
  color: #374151;
}

.decision-metrics {
  display: flex;
  gap: 32px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.metric-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 80px;
}

.metric-item .label {
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
  line-height: 1.4;
}

.metric-item .value {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.4;
}

.decision-reasoning h5 {
  margin: 0 0 8px 0;
  color: #374151;
  font-size: 14px;
}

.decision-reasoning p {
  margin: 0;
  color: #6b7280;
  line-height: 1.6;
}

/* 关键点位参考 */
.key-indicators {
  margin-top: 16px;
  background: #f8fafc;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.key-indicators-title {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 6px;
}

.key-indicators-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.key-indicator-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 8px 12px;
  background: #ffffff;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.key-indicator-label {
  color: #64748b;
  white-space: nowrap;
  flex-shrink: 0;
}

.key-indicator-value {
  color: #1f2937;
  font-weight: 600;
}

.reports-section {
  margin-bottom: 32px;
}

.reports-section h4 {
  color: #1f2937;
  margin-bottom: 16px;
}

.report-content {
  line-height: 1.6;
  color: #374151;
}

.report-content h1,
.report-content h2,
.report-content h3 {
  color: #1f2937;
  margin: 16px 0 8px 0;
}

.report-content strong {
  color: #1f2937;
}

.result-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  padding-top: 24px;
  border-top: 1px solid #e5e7eb;
}

/* 分析报告标签页样式 */
.analysis-tabs-container {
  margin-top: 16px;
}

.analysis-tabs {
  /* 标签页头部样式 */
  :deep(.el-tabs__header) {
    margin: 0 0 20px 0;
    background: var(--el-fill-color-light);
    padding: 12px;
    border-radius: 15px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    border: 1px solid var(--el-border-color);
  }

  /* 标签页导航 */
  :deep(.el-tabs__nav-wrap) {
    &::after {
      display: none; /* 隐藏默认的底部边框 */
    }
  }

  /* 单个标签页样式 */
  :deep(.el-tabs__item) {
    height: 55px !important;
    line-height: 55px !important;
    padding: 0 20px !important;
    margin-right: 8px !important;
    background: var(--el-bg-color) !important;
    border: 2px solid var(--el-border-color) !important;
    border-radius: 12px !important;
    color: var(--el-text-color-regular) !important;
    font-weight: 600 !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
    position: relative !important;
    overflow: hidden !important;
    border-bottom: 2px solid var(--el-border-color) !important; /* 确保底部边框存在 */

    &:hover {
      background: var(--el-fill-color-light) !important;
      border-color: #C5A55A !important;
      transform: translateY(-2px) scale(1.02) !important;
      box-shadow: 0 4px 15px rgba(197,165,90,0.3) !important;
      color: #9E7E3E !important;
    }

    &.is-active {
      background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
      color: white !important;
      border-color: #C5A55A !important;
      box-shadow: 0 6px 20px rgba(197,165,90,0.4) !important;
      transform: translateY(-3px) scale(1.05) !important;

      &::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(135deg, rgba(255,255,255,0.2) 0%, rgba(255,255,255,0.1) 100%);
        border-radius: 10px;
        pointer-events: none;
      }
    }
  }

  /* 标签页内容区域 */
  :deep(.el-tabs__content) {
    padding: 0;
  }

  :deep(.el-tab-pane) {
    padding: 25px;
    background: var(--el-bg-color);
    border-radius: 15px;
    border: 1px solid var(--el-border-color);
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    margin-top: 10px;
  }
}

/* 报告头部样式 */
.report-header {
  margin-bottom: 25px;
  padding: 20px;
  background: var(--el-fill-color-light);
  border-radius: 15px;
  border-left: 5px solid #C5A55A;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);

  .report-title {
    display: flex;
    align-items: center;
    margin-bottom: 8px;

    .report-icon {
      font-size: 24px;
      margin-right: 12px;
    }

    .report-name {
      font-size: 20px;
      font-weight: 700;
      color: #495057;
    }
  }

  .report-description {
    color: #6c757d;
    font-size: 16px;
    line-height: 1.5;
    margin-left: 36px; /* 对齐图标后的文字 */
  }
}

/* 报告内容包装器 */
.report-content-wrapper {
  background: var(--el-bg-color);
  padding: 25px;
  border-radius: 12px;
  border: 1px solid var(--el-border-color);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

/* 报告内容样式增强 */
.report-content {
  line-height: 1.7;
  color: #495057;
  font-size: 16px;

  /* 标题样式 */
  h1, h2, h3, h4, h5, h6 {
    color: #1f2937 !important;
    margin: 20px 0 12px 0 !important;
    font-weight: 600 !important;
  }

  h1 { font-size: 24px !important; }
  h2 { font-size: 20px !important; }
  h3 { font-size: 18px !important; }
  h4 { font-size: 16px !important; }

  /* 段落样式 */
  p {
    margin: 12px 0 !important;
    line-height: 1.7 !important;
  }

  /* 强调文本 */
  strong, b {
    color: #1f2937 !important;
    font-weight: 600 !important;
  }

  /* 斜体文本 */
  em, i {
    color: #4b5563 !important;
    font-style: italic !important;
  }

  /* 列表样式 */
  ul, ol {
    margin: 12px 0 !important;
    padding-left: 24px !important;

    li {
      margin: 6px 0 !important;
      line-height: 1.6 !important;
    }
  }

  /* 代码样式 */
  code {
    background: var(--el-fill-color-light) !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace !important;
    font-size: 14px !important;
    color: #e11d48 !important;
  }

  /* 引用样式 */
  blockquote {
    border-left: 4px solid #C5A55A !important;
    padding-left: 16px !important;
    margin: 16px 0 !important;
    background: var(--el-fill-color-light) !important;
    padding: 12px 16px !important;
    border-radius: 0 8px 8px 0 !important;
    font-style: italic !important;
    color: var(--el-text-color-regular) !important;
  }
}

/* 风险提示样式 */
.risk-disclaimer {
  margin-top: 24px;
  border-radius: 8px;

  :deep(.el-alert__content) {
    width: 100%;
  }

  :deep(.el-alert__title) {
    font-size: 14px;
    line-height: 1.6;
    color: #e6a23c;
  }
}
</style>
