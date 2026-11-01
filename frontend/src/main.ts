import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { campusUi } from './ui'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import './style.css'
import App from './App.vue'
import './styles/typography.css'

createApp(App).use(createPinia()).use(campusUi).mount('#app')

// Installable web client (Android/iOS/home-screen) — never inside the Electron shell, where
// the packaged frontend is served locally and offline behaviour is already guaranteed.
if (import.meta.env.PROD && !window.campusDesktop && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => { /* offline shell is optional */ })
  })
}
