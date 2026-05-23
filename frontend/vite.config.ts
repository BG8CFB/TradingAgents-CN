import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: [
        'vue',
        'vue-router',
        'pinia',
        '@vueuse/core'
      ],
      dts: true,
      eslintrc: {
        enabled: true
      }
    }),
    // 自动按需组件导入
    Components({
      resolvers: [ElementPlusResolver()],
      dts: true
    })
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@components': resolve(__dirname, 'src/components'),
      '@views': resolve(__dirname, 'src/views'),
      '@stores': resolve(__dirname, 'src/stores'),
      '@utils': resolve(__dirname, 'src/utils'),
      '@types': resolve(__dirname, 'src/types'),
      '@api': resolve(__dirname, 'src/api')
    }
  },
  optimizeDeps: {
    include: [
      'vue',
      'vue-router',
      'pinia',
      '@vueuse/core',
      'element-plus/es',
      'element-plus/es/components/base/style/css',
      'element-plus/es/components/select/style/css',
      'element-plus/es/components/option/style/css',
      'element-plus/es/components/empty/style/css',
      'element-plus/es/components/tag/style/css',
      'element-plus/es/components/input/style/css',
      'element-plus/es/components/icon/style/css',
      'element-plus/es/components/dialog/style/css',
      'element-plus/es/components/button/style/css',
      'element-plus/es/components/descriptions/style/css',
      'element-plus/es/components/descriptions-item/style/css',
      'element-plus/es/components/link/style/css',
      'element-plus/es/components/form/style/css',
      'element-plus/es/components/form-item/style/css',
      'element-plus/es/components/divider/style/css',
      'element-plus/es/components/alert/style/css',
      'element-plus/es/components/steps/style/css',
      'element-plus/es/components/step/style/css',
      'element-plus/es/components/backtop/style/css',
      'element-plus/es/components/row/style/css',
      'element-plus/es/components/col/style/css',
      'element-plus/es/components/table/style/css',
      'element-plus/es/components/table-column/style/css',
      'element-plus/es/components/card/style/css',
      'element-plus/es/components/breadcrumb/style/css',
      'element-plus/es/components/breadcrumb-item/style/css',
      'element-plus/es/components/menu/style/css',
      'element-plus/es/components/sub-menu/style/css',
      'element-plus/es/components/menu-item/style/css',
      'element-plus/es/components/dropdown/style/css',
      'element-plus/es/components/dropdown-menu/style/css',
      'element-plus/es/components/dropdown-item/style/css',
      'element-plus/es/components/avatar/style/css',
      'element-plus/es/components/drawer/style/css',
      'element-plus/es/components/scrollbar/style/css',
      'element-plus/es/components/segmented/style/css',
      'element-plus/es/components/badge/style/css',
      'element-plus/es/components/tooltip/style/css',
      'element-plus/es/components/loading/style/css',
      'element-plus/es/components/progress/style/css',
      'element-plus/es/components/text/style/css',
      'element-plus/es/components/checkbox/style/css',
      'element-plus/es/components/tabs/style/css',
      'element-plus/es/components/tab-pane/style/css',
      'element-plus/es/components/input-number/style/css',
      'element-plus/es/components/switch/style/css',
      'element-plus/es/components/date-picker/style/css',
      'element-plus/es/components/upload/style/css',
      'element-plus/es/components/collapse/style/css',
      'element-plus/es/components/collapse-item/style/css',
      'element-plus/es/components/radio-group/style/css',
      'element-plus/es/components/radio/style/css',
      'element-plus/es/components/checkbox-group/style/css',
      'element-plus/es/components/pagination/style/css',
      'element-plus/es/components/slider/style/css',
      'element-plus/es/components/radio-button/style/css',
      'element-plus/es/components/skeleton/style/css',
      'element-plus/es/components/timeline/style/css',
      'element-plus/es/components/timeline-item/style/css',
      'element-plus/es/components/statistic/style/css',
      'element-plus/es/components/button-group/style/css',
      'element-plus/es/components/popover/style/css',
      'element-plus/es/components/image/style/css',
      'element-plus/es/components/result/style/css',
      'element-plus/es/components/notification/style/css',
      'element-plus/es/components/message-box/style/css',
      'element-plus/es/components/message/style/css',
    ]
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    hmr: {
      overlay: false
    },
    // 允许从项目根目录之外（例如 /docs）导入原始文件
    fs: {
      allow: [resolve(__dirname, '..')]
    },
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        ws: true
      }
    }
  },
  build: {
    target: 'es2020',  // 支持 nullish coalescing operator (??) 和 optional chaining (?.)
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    rollupOptions: {
      output: {
        chunkFileNames: 'js/[name]-[hash].js',
        entryFileNames: 'js/[name]-[hash].js',
        assetFileNames: '[ext]/[name]-[hash].[ext]'
      }
    }
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern',
        additionalData: `@use "@/styles/variables.scss" as *;`
      }
    }
  }
})
