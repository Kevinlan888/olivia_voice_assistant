import { createApp } from 'vue'
import App from './App.vue'

async function bootstrap() {
  // vConsole: enabled in dev, or in production via ?vconsole query param.
  // On device: open https://<host>/?vconsole to get the debug panel.
  if (import.meta.env.DEV || new URLSearchParams(location.search).has('vconsole')) {
    const { default: VConsole } = await import('vconsole')
    new VConsole()
  }
  createApp(App).mount('#app')
}

bootstrap()
