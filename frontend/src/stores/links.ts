import { reactive } from 'vue'
import { api, type Link, type LinkInput } from '../api'

const state = reactive<{ items: Link[]; loaded: boolean }>({ items: [], loaded: false })

export const links = {
  state,

  byId(id: number) {
    return state.items.find((link) => link.id === id)
  },

  async load() {
    state.items = await api<Link[]>('GET', '/api/links')
    state.loaded = true
  },

  async create(input: LinkInput) {
    const link = await api<Link>('POST', '/api/links', input)
    state.items.push(link)
    return link
  },

  async update(id: number, input: LinkInput) {
    const link = await api<Link>('PUT', `/api/links/${id}`, input)
    state.items = state.items.map((item) => (item.id === id ? link : item))
    return link
  },

  async remove(id: number) {
    await api('DELETE', `/api/links/${id}`)
    state.items = state.items.filter((item) => item.id !== id)
  },

  async reorder(ids: number[]) {
    state.items = await api<Link[]>('PUT', '/api/links/order', { ids })
  },
}
