<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <v-app>
    <v-toolbar floating :elevation="3">
      <div class="toolbar-content">
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
.toolbar-content {
  width: 100%;
  display: flex;
  justify-content: center;
  padding: 30px;
}

.app-title {
  font-size: 50px !important;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.main-content-container {
  padding: 5vh;
  min-height: 100%;
}
</style>
