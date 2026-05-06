import { ApiClient } from './request'
import type {
  LoginForm,
  RegisterForm,
  LoginResponse,
  RefreshTokenResponse,
  User,
  ChangePasswordForm
} from '@/types/auth'

export const authApi = {
  // 登录
  login: (data: LoginForm) =>
    ApiClient.post<LoginResponse>('/api/auth/login', data, {
      skipAuth: true,  // 登录请求不需要认证
      skipAuthError: true  // 跳过 401 错误的自动处理
    }),

  // 注册
  register: (data: RegisterForm) =>
    ApiClient.post('/api/auth/register', data, {
      skipAuth: true,  // 注册请求不需要认证
      skipAuthError: true  // 跳过 401 错误的自动处理
    }),

  // 登出
  logout: () =>
    ApiClient.post('/api/auth/logout'),

  // 刷新Token
  refreshToken: (refreshToken: string) =>
    ApiClient.post<RefreshTokenResponse>('/api/auth/refresh', { refresh_token: refreshToken }),

  // 获取用户信息
  getUserInfo: () =>
    ApiClient.get<User>('/api/auth/me'),

  // 获取用户权限（开源版不需要，admin拥有所有权限）
  // getUserPermissions: () =>
  //   ApiClient.get<UserPermissions>('/api/auth/permissions'),

  // 更新用户信息
  updateUserInfo: (data: Partial<User>) =>
    ApiClient.put<User>('/api/auth/me', data),

  // 修改密码
  changePassword: (data: ChangePasswordForm) =>
    ApiClient.post('/api/auth/change-password', data),

  // 管理员重置用户密码（需要管理员权限）
  adminResetPassword: (username: string, newPassword: string) =>
    ApiClient.post('/api/auth/reset-password', { username, new_password: newPassword })
}
