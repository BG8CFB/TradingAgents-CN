import { defineStore } from 'pinia'
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

  const installFromGit = async (url: string, trustedHosts?: string[]) => {
    try {
      const res = await skillsApi.installFromGit(url, trustedHosts)
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
    uninstallSkill,
  }
})
