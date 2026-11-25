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
      path: '/face-auth',
      name: 'face-auth',
      component: FaceAuthView,
    },
  ],
})

export default router
