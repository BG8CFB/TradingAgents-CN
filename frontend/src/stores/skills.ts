import { defineStore } from 'pinia'

// 安装轮询上限（后端任务可能持续数分钟）
const INSTALL_POLL_TIMEOUT = 10 * 60 * 1000
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  skillsApi,
  type SkillSummary,
  type SkillDetail,
  type SkillGlobalConfig,
  type InstallLog,
} from '@/api/skills'

export const useSkillsStore = defineStore('skills', () => {
  const skills = ref<SkillSummary[]>([])
  const loading = ref(false)
  const config = ref<SkillGlobalConfig | null>(null)
  const currentDetail = ref<SkillDetail | null>(null)
  const installLogs = ref<InstallLog[]>([])

  const total = computed(() => skills.value.length)
  const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)
  const scriptCount = computed(() => skills.value.filter((s) => s.has_scripts).length)
  const needsInstallCount = computed(
    () => skills.value.filter((s) => s.dependencies_missing > 0).length
  )

  const fetchSkills = async () => {
    loading.value = true
    try {
      const res = await skillsApi.list()
      if (res.success && res.data) {
        skills.value = res.data.skills
      }
    } catch (e) {
      console.error('加载 skill 列表失败', e)
      ElMessage.error('加载 skill 列表失败')
    } finally {
      loading.value = false
    }
  }

  const fetchConfig = async () => {
    try {
      const res = await skillsApi.getConfig()
      if (res.success && res.data) {
        config.value = res.data
      }
    } catch (e) {
      console.error('加载 skill 配置失败', e)
    }
  }

  const fetchDetail = async (name: string) => {
    try {
      const res = await skillsApi.getDetail(name)
      if (res.success && res.data) {
        currentDetail.value = res.data
        return res.data
      }
    } catch (e) {
      console.error('加载 skill 详情失败', e)
      ElMessage.error('加载 skill 详情失败')
    }
    return null
  }

  const fetchInstallLogs = async (skillName?: string) => {
    try {
      const res = await skillsApi.listInstallLogs(skillName)
      if (res.success && res.data) {
        installLogs.value = res.data.logs
      }
    } catch (e) {
      console.error('加载安装日志失败', e)
    }
  }

  const toggleSkill = async (name: string, enabled: boolean) => {
    const skill = skills.value.find((s) => s.name === name)
    const original = skill?.enabled
    if (skill) {
      skill.enabled = enabled
    }
    try {
      await skillsApi.toggle(name, enabled)
      ElMessage.success(enabled ? '已启用' : '已禁用')
    } catch (e) {
      if (skill && original !== undefined) {
        skill.enabled = original
      }
      ElMessage.error('切换失败')
      throw e
    }
  }

  const installSkill = async (name: string) => {
    try {
      const res = await skillsApi.install(name)
      if (res.success) {
        ElMessage.success(`依赖安装完成: ${res.data.packages_installed?.length || 0} 个包`)
        await fetchSkills()
      }
      return res
    } catch (e) {
      ElMessage.error('依赖安装失败')
      throw e
    }
  }

  const checkSkill = async (name: string) => {
    try {
      const res = await skillsApi.check(name)
      return res.data
    } catch (e) {
      console.error('检查失败', e)
    }
    return null
  }

  const reloadSkills = async () => {
    try {
      const res = await skillsApi.reload()
      if (res.success) {
        ElMessage.success(`重新扫描完成，发现 ${res.data.total} 个 skill`)
        await fetchSkills()
      }
    } catch (e) {
      ElMessage.error('重新扫描失败')
    }
  }

  const installFromGit = async (url: string) => {
    try {
      const res = await skillsApi.installFromGit(url)
      if (res.success) {
        ElMessage.success(`已安装: ${res.data.skill_name}`)
        await fetchSkills()
      }
      return res
    } catch (e) {
      ElMessage.error('Git 安装失败')
      throw e
    }
  }

  const installFromLocalPath = async (path: string) => {
    try {
      const res = await skillsApi.installFromLocalPath(path)
      if (res.success) {
        ElMessage.success(`已导入: ${res.data.skill_name}`)
        await fetchSkills()
      }
      return res
    } catch (e) {
      ElMessage.error('本地路径导入失败')
      throw e
    }
  }

  const installUpload = async (file: File) => {
    try {
      const res = await skillsApi.installUpload(file)
      if (res.success) {
        ElMessage.success(`已安装: ${res.data.skill_name}`)
        await fetchSkills()
      }
      return res
    } catch (e) {
      ElMessage.error('zip 安装失败')
      throw e
    }
  }

  // ── ClawHub 市场：引导去官网找技能，安装统一走粘贴命令（installFromReference） ──

  /** 粘贴安装命令/引用一键安装（后台任务 + 轮询，不阻塞界面） */
  const installFromReference = async (reference: string) => {
    const submit = await skillsApi.installFromReference(reference)
    if (!submit.success || !submit.data?.task_id) {
      return submit
    }
    const taskId = submit.data.task_id
    // 轮询直到完成（慢网下市场/Git 下载可达分钟级；提交已即时返回，界面不卡）
    const deadline = Date.now() + INSTALL_POLL_TIMEOUT
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const res = await skillsApi.installReferenceStatus(taskId)
        if (res.success && res.data?.status === 'done') {
          const result = res.data.result || {}
          if (result.success) {
            ElMessage.success(`已安装: ${result.skill_name}`)
            await fetchSkills()
          } else {
            ElMessage.error(result.error || '安装失败')
          }
          return result
        }
      } catch (e) {
        console.error('查询安装任务状态失败', e)
      }
    }
    ElMessage.warning('安装仍在后台执行，稍后请手动刷新列表查看结果')
    return { success: false, error: '安装仍在后台执行' }
  }

  const uninstallSkill = async (name: string, force = false) => {
    try {
      const res = await skillsApi.uninstall(name, force)
      if (res.success) {
        ElMessage.success(`已卸载: ${name}`)
        await fetchSkills()
      }
      return res
    } catch (e) {
      ElMessage.error('卸载失败')
      throw e
    }
  }

  return {
    skills,
    loading,
    config,
    currentDetail,
    installLogs,
    total,
    enabledCount,
    scriptCount,
    needsInstallCount,
    fetchSkills,
    fetchConfig,
    fetchDetail,
    fetchInstallLogs,
    toggleSkill,
    installSkill,
    checkSkill,
    reloadSkills,
    installFromGit,
    installFromLocalPath,
    installUpload,
    installFromReference,
    uninstallSkill,
  }
})
