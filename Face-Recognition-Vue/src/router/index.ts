import { createRouter, createWebHistory } from 'vue-router'
import FaceAuthView from '../components/FaceAuthView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/face-auth',
      name: 'face-auth',
      component: FaceAuthView,
    },
  ],
})

export default router
