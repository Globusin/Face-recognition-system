<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <v-app>
    <v-toolbar floating :elevation="3">
      <div class="w-100 d-flex justify-center">
        <span class="app-title">Домовой</span>
      </div>
    </v-toolbar>

    <v-main>
      <div class="main-content-container">
        <RouterView />
      </div>
    </v-main>
  </v-app>
</template>

<style scoped>
.app-title {
  font-size: 50px !important;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #5d4037;
}

.main-content-container {
  padding: 5vh;
  min-height: 100%;
}
</style>
