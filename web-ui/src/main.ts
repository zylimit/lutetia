import { createApp } from 'vue'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/base.css'
import './theme' // applies the stored or system theme before the first paint of the app
import App from './App.vue'
import { router } from './router'

createApp(App).use(router).mount('#app')
