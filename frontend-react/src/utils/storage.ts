/**
 * 类型安全的 localStorage 封装
 */
export const storage = {
  get<T>(key: string): T | null {
    try {
      const value = localStorage.getItem(key)
      if (value === null) return null
      return JSON.parse(value) as T
    } catch {
      return null
    }
  },

  set<T>(key: string, value: T): void {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      console.warn(`Failed to set localStorage key: ${key}`)
    }
  },

  remove(key: string): void {
    localStorage.removeItem(key)
  },

  clear(): void {
    localStorage.clear()
  },
}

/**
 * 会话存储（关闭浏览器即清除）
 */
export const sessionStorage = {
  get<T>(key: string): T | null {
    try {
      const value = window.sessionStorage.getItem(key)
      if (value === null) return null
      return JSON.parse(value) as T
    } catch {
      return null
    }
  },

  set<T>(key: string, value: T): void {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value))
    } catch {
      console.warn(`Failed to set sessionStorage key: ${key}`)
    }
  },

  remove(key: string): void {
    window.sessionStorage.removeItem(key)
  },
}
