import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api'
import { session } from './stores/session'

// Any API call answered with 401 (expired session, deactivated user) returns to the login page.
setUnauthorizedHandler(() => {
  session.clear()
  if (router.currentRoute.value.path !== '/login') {
    router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})

createApp(App).use(router).mount('#app')
