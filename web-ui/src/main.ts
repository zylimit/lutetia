import { createApp } from 'vue'
import './styles/fonts.css'
import './styles/base.css'
import App from './App.vue'
import { router } from './router'

createApp(App).use(router).mount('#app')
