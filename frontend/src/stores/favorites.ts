import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { favoritesApi, type FavoriteItem } from '@/api/favorites'

/**
 * 自选股全局缓存 store。
 *
 * 设计目标：Dashboard / Favorites / Screening 等多个页面共享同一份自选股列表，
 * 避免同一帧内多个组件各自调用 favoritesApi.list() 造成的重复请求。
 *
 * 并发去重：fetch 期间若有第二次调用，复用同一个 in-flight Promise，
 * 而不是发起新请求（Dashboard 首屏 loadStats 与 loadFavoriteStocks 并行触发的场景）。
 */
export const useFavoritesStore = defineStore('favorites', () => {
  const items = ref<FavoriteItem[]>([])
  const loaded = ref(false)
  // 模块级变量持有正在进行的请求，用于并发去重（不放入响应式 state）
  let pending: Promise<FavoriteItem[]> | null = null

  const count = computed(() => items.value.length)

  /**
   * 拉取自选股列表。
   * @param force 为 true 时强制刷新，跳过缓存与并发去重
   */
  async function fetch(force = false): Promise<FavoriteItem[]> {
    // 已加载且非强制刷新：直接返回缓存
    if (loaded.value && !force) {
      return items.value
    }
    // 已有进行中的请求：复用，避免重复发请求
    if (pending && !force) {
      return pending
    }

    pending = (async () => {
      try {
        const response = await favoritesApi.list()
        const list = response.success && response.data ? response.data : []
        items.value = list
        loaded.value = true
        return list
      } finally {
        pending = null
      }
    })()

    return pending
  }

  /** 标记缓存失效，下次 fetch 会重新拉取 */
  function invalidate() {
    loaded.value = false
  }

  /** 添加自选后刷新缓存 */
  async function add(payload: Parameters<typeof favoritesApi.add>[0]) {
    const res = await favoritesApi.add(payload)
    await fetch(true)
    return res
  }

  /** 更新自选后刷新缓存 */
  async function update(symbol: string, payload: Parameters<typeof favoritesApi.update>[1]) {
    const res = await favoritesApi.update(symbol, payload)
    await fetch(true)
    return res
  }

  /** 删除自选后刷新缓存 */
  async function remove(symbol: string) {
    const res = await favoritesApi.remove(symbol)
    await fetch(true)
    return res
  }

  return {
    items,
    loaded,
    count,
    fetch,
    invalidate,
    add,
    update,
    remove,
  }
})
