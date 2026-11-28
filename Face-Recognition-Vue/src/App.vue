<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
const route = useRoute()
</script>

<template>
  <v-app>
    <header class="app-header">
      <div class="header-inner">
        <RouterLink to="/" class="brand">Домовой</RouterLink>
        <span class="header-caption">{{ route.name === 'admin' ? 'Администрирование' : 'Контроль доступа' }}</span>
        <v-spacer />
        <v-btn v-if="route.name === 'admin'" to="/" variant="text" size="small">К экрану прохода</v-btn>
        <v-btn v-else to="/admin" variant="text" size="small">Вход администратора</v-btn>
      </div>
    </header>
    <v-main>
      <RouterView />
    </v-main>
  </v-app>
</template>

<style scoped>
.app-header { background: rgb(var(--v-theme-surface)); border-bottom: 1px solid #dce1e5; }
.header-inner { max-width: 1440px; margin: auto; min-height: 64px; padding: 8px 24px; display: flex; align-items: center; gap: 16px; }
.brand { color: rgb(var(--v-theme-on-surface)); font-size: 20px; font-weight: 700; text-decoration: none; }
.header-caption { color: #56616c; font-size: 13px; border-left: 1px solid #dce1e5; padding-left: 16px; }
@media (max-width: 600px) { .header-inner { padding: 8px 12px; gap: 8px; } .header-caption { display: none; } }
</style>
