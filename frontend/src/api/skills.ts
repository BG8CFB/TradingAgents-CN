import { request, type ApiResponse } from './request'

export interface SkillDependencyStatus {
  package: string
  version_constraint: string
  satisfied: boolean
  installed_version: string
  note: string
}

export interface SkillAvailability {
  skill_name: string
  enabled: boolean
  dependencies_satisfied: boolean
  dependencies: SkillDependencyStatus[]
  env_satisfied: boolean
  missing_env: string[]
  entrypoints_available: string[]
  entrypoints_unavailable: string[]
  warnings: string[]
}

export interface SkillSummary {
  name: string
  description: string
  version: string
  user_invocable: boolean
  enabled: boolean
  source_type: 'local' | 'builtin' | 'git' | 'registry'
  has_scripts: boolean
  has_manifest: boolean
  entrypoint_count: number
  dependencies_satisfied: boolean
  dependencies_total: number
  dependencies_missing: number
}

export interface SkillDetail {
  name: string
  description: string
  version: string
  user_invocable: boolean
  enabled: boolean
  source_type: string
  has_scripts: boolean
  has_manifest: boolean
  path: string
  skill_dir: string
  entrypoints: any[]
  availability: SkillAvailability
  content_preview: string
}

export interface InstallLog {
  id?: string
  skill_name: string
  source_url: string
  source_commit: string
  packages: { package: string; version: string; hash: string }[]
  status: 'success' | 'failed' | 'partial'
  error: string
  duration_seconds: number
  installed_by: string
  installed_at: string
}

export interface SkillGlobalConfig {
  auto_install: boolean
  allowed_packages: string[]
  install_timeout: number
  registry_url: string
  git_trusted_hosts: string[]
}

export const skillsApi = {
  list(): Promise<ApiResponse<{ skills: SkillSummary[]; total: number }>> {
    return request.get('/api/skills')
  },

  getConfig(): Promise<ApiResponse<SkillGlobalConfig>> {
    return request.get('/api/skills/config')
  },

  getDetail(name: string): Promise<ApiResponse<SkillDetail>> {
    return request.get(`/api/skills/${name}`)
  },

  getContent(name: string): Promise<ApiResponse<{ name: string; content: string }>> {
    return request.get(`/api/skills/${name}/content`)
  },

  toggle(name: string, enabled: boolean): Promise<ApiResponse<any>> {
    return request.post(`/api/skills/${name}/toggle`, { enabled })
  },

  check(name: string): Promise<ApiResponse<SkillAvailability>> {
    return request.post(`/api/skills/${name}/check`)
  },

  install(name: string): Promise<ApiResponse<any>> {
    return request.post(`/api/skills/${name}/install`)
  },

  reload(): Promise<ApiResponse<any>> {
    return request.post('/api/skills/reload')
  },

  installFromGit(
    url: string,
    trusted_hosts?: string[]
  ): Promise<ApiResponse<any>> {
    return request.post('/api/skills/install/git', { url, trusted_hosts })
  },

  installFromRegistry(name: string, version?: string): Promise<ApiResponse<any>> {
    return request.post('/api/skills/install/registry', { name, version })
  },

  uninstall(name: string, force = false): Promise<ApiResponse<any>> {
    return request.delete(`/api/skills/${name}`, { params: { force } })
  },

  listInstallLogs(
    skillName?: string,
    limit = 100
  ): Promise<ApiResponse<{ logs: InstallLog[]; total: number }>> {
    return request.get('/api/skills/install-logs', {
      params: { skill_name: skillName, limit },
    })
  },
}
