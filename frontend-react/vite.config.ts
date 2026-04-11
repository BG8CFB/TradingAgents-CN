import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
      '@components': resolve(__dirname, './src/components'),
      '@pages': resolve(__dirname, './src/pages'),
      '@features': resolve(__dirname, './src/features'),
      '@hooks': resolve(__dirname, './src/hooks'),
      '@stores': resolve(__dirname, './src/stores'),
      '@services': resolve(__dirname, './src/services'),
      '@utils': resolve(__dirname, './src/utils'),
      '@types': resolve(__dirname, './src/types'),
      '@config': resolve(__dirname, './src/constants'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      // 统一代理：所有后端 API 均通过 /api 前缀访问
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: 'chrome80',
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) return 'react-vendor'
          if (id.includes('node_modules/react-router')) return 'router'
          if (id.includes('node_modules/antd') || id.includes('node_modules/@ant-design')) return 'ui'
          if (id.includes('node_modules/zustand')) return 'state'
          if (id.includes('node_modules/echarts')) return 'charts'
          if (id.includes('node_modules/react-hook-form') || id.includes('node_modules/zod')) return 'form'
          return 'vendor'
        },
      },
    },
  },
})
