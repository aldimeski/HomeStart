import { createRouter, createWebHistory } from 'vue-router'
import { session } from './stores/session'
import AppLayout from './layouts/app-layout.vue'
import LoginView from './views/login-view.vue'
import HomeView from './views/home-view.vue'
import LinkFrameView from './views/link-frame-view.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', component: HomeView },
        { path: 'link/:id', component: LinkFrameView, props: true },
        { path: 'tasmosiz', component: () => import('./views/tasmosiz-view.vue') },
        { path: 'skoda', component: () => import('./views/skoda-view.vue') },
        { path: 'radiopanel', component: () => import('./views/radio-view.vue') },
        {
          path: 'config',
          component: () => import('./views/config/config-layout.vue'),
          children: [
            { path: '', redirect: () => (session.isAdmin.value ? '/config/links' : '/config/account') },
            { path: 'links', component: () => import('./views/config/links-config.vue'), meta: { admin: true } },
            { path: 'users', component: () => import('./views/config/users-config.vue'), meta: { admin: true } },
            { path: 'devices', component: () => import('./views/config/devices-config.vue'), meta: { admin: true } },
            { path: 'radio', component: () => import('./views/config/radio-config.vue'), meta: { admin: true } },
            { path: 'account', component: () => import('./views/config/my-account.vue') },
          ],
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  if (!session.state.loaded) await session.load()
  const loggedIn = !!session.state.user

  if (to.meta.public) return loggedIn ? '/' : true
  if (!loggedIn) return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  if (to.meta.admin && !session.isAdmin.value) return '/config/account'
  return true
})
