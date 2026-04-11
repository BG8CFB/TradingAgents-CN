import type { ApiResponse } from './common.types'

export interface User {
  id: string
  username: string
  email: string
  is_active: boolean
  is_verified: boolean
  is_admin: boolean
  created_at: string
  updated_at: string
  last_login?: string
  avatar?: string
  preferences?: UserPreferences
  permissions?: string[]
  roles?: string[]
}

export interface UserPreferences {
  default_market?: string
  default_depth?: string
  default_analysts?: string[]
  auto_refresh?: boolean
  refresh_interval?: number
  ui_theme?: 'light' | 'dark' | 'auto'
  language?: string
  notifications_enabled?: boolean
}

export interface LoginForm {
  username: string
  password: string
  remember?: boolean
}

export interface RegisterForm {
  username: string
  email: string
  password: string
  confirmPassword?: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface AuthApi {
  login: (form: LoginForm) => Promise<ApiResponse<LoginResponse>>
  register: (form: RegisterForm) => Promise<ApiResponse<unknown>>
  logout: () => Promise<ApiResponse<unknown>>
  getUserInfo: () => Promise<ApiResponse<User>>
  updateUserInfo: (data: Partial<User>) => Promise<ApiResponse<User>>
  changePassword: (data: { old_password: string; new_password: string }) => Promise<ApiResponse<unknown>>
  refreshToken: (refreshToken: string) => Promise<ApiResponse<{ access_token: string; refresh_token?: string }>>
}
