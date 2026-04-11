import type { ApiResponse } from '@/types/common.types'
import type { LoginForm, LoginResponse, RegisterForm, User } from '@/types/auth.types'
import apiClient from '../http/client'

export function login(form: LoginForm): Promise<ApiResponse<LoginResponse>> {
  return apiClient.post('/api/auth/login', form, { skipAuth: true })
}

export function register(form: RegisterForm): Promise<ApiResponse<unknown>> {
  return apiClient.post('/api/auth/register', form, { skipAuth: true })
}

export function logout(): Promise<ApiResponse<unknown>> {
  return apiClient.post('/api/auth/logout')
}

export function getUserInfo(): Promise<ApiResponse<User>> {
  return apiClient.get('/api/auth/me')
}

export function updateUserInfo(data: Partial<User>): Promise<ApiResponse<User>> {
  return apiClient.put('/api/auth/me', data)
}

export function changePassword(data: { old_password: string; new_password: string }): Promise<ApiResponse<unknown>> {
  return apiClient.post('/api/auth/change-password', data)
}

export function refreshToken(token: string): Promise<ApiResponse<{ access_token: string; refresh_token?: string }>> {
  return apiClient.post('/api/auth/refresh', { refresh_token: token }, { skipAuth: true })
}
