<template>
  <el-dialog
    :model-value="modelValue"
    title="添加技能"
    width="720px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-tabs v-model="activeTab">
      <!-- Git 安装 -->
      <el-tab-pane label="Git" name="git">
        <el-form label-position="top" @submit.prevent>
          <el-form-item label="Git URL（https）">
            <el-input
              v-model="gitUrl"
              placeholder="https://github.com/user/my-skill.git"
              @keyup.enter="handleGitInstall"
            />
          </el-form-item>
        </el-form>
        <div class="tab-footer">
          <el-button
            type="primary"
            :loading="gitInstalling"
            :disabled="!gitUrl.trim()"
            @click="handleGitInstall"
          >
            安装
          </el-button>
        </div>
      </el-tab-pane>

      <!-- 本地添加：zip 上传 / 服务器路径导入 -->
      <el-tab-pane label="本地" name="local">
        <el-upload
          drag
          accept=".zip"
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onZipSelected"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽 zip 包到此处，或<em>点击选择</em></div>
          <template #tip>
            <div class="el-upload__tip">
              zip 根目录（或唯一子目录）需含 SKILL.md，大小不超过
              {{ maxUploadMb }}MB
            </div>
          </template>
        </el-upload>
        <el-divider>或从服务器目录导入</el-divider>
        <div class="path-row">
          <el-input
            v-model="localPath"
            placeholder="服务器上的 skill 目录绝对路径，如 /home/user/my-skill"
            @keyup.enter="handleLocalPathInstall"
          />
          <el-button
            type="primary"
            :loading="localInstalling"
            :disabled="!localPath.trim()"
            @click="handleLocalPathInstall"
          >
            导入
          </el-button>
        </div>
      </el-tab-pane>

      <!-- ClawHub 市场：官网浏览 + 粘贴安装命令（官网搜索/分类更全，本地搜索是关键词匹配，
           不支持 owner/slug 引用，故不再提供，统一引导去官网找技能后复制安装命令回来） -->
      <el-tab-pane label="市场" name="market">
        <div>
          <div class="market-jump">
            <div class="market-jump-text">
              <div class="market-jump-title">前往 ClawHub 技能市场挑选技能</div>
              <div class="market-jump-desc">
                在官网找到需要的技能后，复制其安装命令粘贴到下方即可安装（支持
                <code>@owner/slug</code>、<code>skills-sh:owner/repo/subdir</code>、Git URL）
              </div>
            </div>
            <el-button type="primary" tag="a" href="https://clawhub.ai/" target="_blank" rel="noopener noreferrer">
              打开 clawhub.ai
              <el-icon class="market-jump-icon"><TopRight /></el-icon>
            </el-button>
          </div>
          <div class="market-paste-row">
            <el-input
              v-model="referenceInput"
              placeholder="粘贴安装命令，如 openclaw skills install skills-sh:vercel-labs/skills/find-skills"
              clearable
              @keyup.enter="handleReferenceInstall"
            />
            <el-button
              type="primary"
              :loading="referenceInstalling"
              :disabled="!referenceInput.trim()"
              @click="handleReferenceInstall"
            >
              安装
            </el-button>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { TopRight, UploadFilled } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { useSkillsStore } from '@/stores/skills'

defineProps<{ modelValue: boolean }>()
defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const skillsStore = useSkillsStore()
const activeTab = ref('git')

// ── Git ──
const gitUrl = ref('')
const gitInstalling = ref(false)

const GIT_URL_RE = /^https:\/\/[\w.-]+\/[\w.-]+\/[\w.-]+?(?:\.git)?\/?$/

const handleGitInstall = async () => {
  const url = gitUrl.value.trim()
  if (!url) {
    ElMessage.warning('请输入 Git URL')
    return
  }
  if (!url.startsWith('https://')) {
    ElMessage.warning('仅支持 https:// 协议的 Git URL（拒绝 file://、ssh:// 等）')
    return
  }
  if (!GIT_URL_RE.test(url)) {
    ElMessage.warning('Git URL 格式不正确，应为 https://host/owner/repo（可带 .git 后缀）')
    return
  }
  gitInstalling.value = true
  try {
    await skillsStore.installFromGit(url)
    gitUrl.value = ''
  } catch {
    // 错误已在 store 中处理
  } finally {
    gitInstalling.value = false
  }
}

// ── 本地 ──
const localPath = ref('')
const localInstalling = ref(false)
const zipInstalling = ref(false)
// 与后端 SKILL_UPLOAD_MAX_SIZE_MB 默认值一致（超限由后端 413 兜底）
const maxUploadMb = 20

const onZipSelected = async (file: UploadFile) => {
  const raw = file.raw
  if (!raw) return
  if (!raw.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('仅支持 .zip 文件')
    return
  }
  if (raw.size > maxUploadMb * 1024 * 1024) {
    ElMessage.warning(`文件超过 ${maxUploadMb}MB 上限`)
    return
  }
  zipInstalling.value = true
  try {
    await skillsStore.installUpload(raw)
  } catch {
    // 错误已在 store 中处理
  } finally {
    zipInstalling.value = false
  }
}

const handleLocalPathInstall = async () => {
  const path = localPath.value.trim()
  if (!path) {
    ElMessage.warning('请输入服务器目录路径')
    return
  }
  localInstalling.value = true
  try {
    await skillsStore.installFromLocalPath(path)
    localPath.value = ''
  } catch {
    // 错误已在 store 中处理
  } finally {
    localInstalling.value = false
  }
}

// ── 市场：官网跳转 + 粘贴安装命令，无本地列表 ──

// ── 粘贴安装命令（openclaw skills install X / @owner/slug / skills-sh:owner/repo/subdir / git URL） ──
const referenceInput = ref('')
const referenceInstalling = ref(false)

const handleReferenceInstall = async () => {
  const ref = referenceInput.value.trim()
  if (!ref) {
    ElMessage.warning('请粘贴安装命令或安装引用')
    return
  }
  referenceInstalling.value = true
  try {
    await skillsStore.installFromReference(ref)
    referenceInput.value = ''
  } catch {
    // 错误已在 store 中处理
  } finally {
    referenceInstalling.value = false
  }
}
</script>

<style scoped>
.tab-footer {
  text-align: right;
}
.path-row {
  display: flex;
  gap: 12px;
}
.market-empty {
  padding: 24px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
}
.market-jump {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.market-jump-title {
  font-weight: 600;
}
.market-jump-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.market-jump-icon {
  margin-left: 4px;
}
.market-paste-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.market-home-link {
  margin-left: 4px;
  font-size: 12px;
  vertical-align: middle;
}
.market-list {
  min-height: 120px;
  max-height: 420px;
  overflow-y: auto;
}
.market-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.market-item-main {
  flex: 1;
  min-width: 0;
}
.market-item-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.market-name {
  font-weight: 600;
}
.market-installed {
  color: var(--el-color-success);
  font-size: 12px;
}
.market-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.market-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  gap: 12px;
}
.market-link {
  color: var(--el-color-primary);
  text-decoration: none;
}
.market-more {
  margin-top: 12px;
  text-align: center;
}
</style>
