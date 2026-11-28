import { createRouter, createWebHistory } from 'vue-router'
import FaceAuthView from '../components/FaceAuthView.vue'
import StatusPanel from '../components/StatusPanel.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'status',
      component: StatusPanel,
    },
    {
      path: '/admin',
      alias: '/face-auth',
      name: 'admin',
      component: FaceAuthView,
    },
  ],
})

export default router
