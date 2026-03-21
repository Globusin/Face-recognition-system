<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <v-app>
    <v-toolbar floating :border="true" color="#060a16">
      <div style="display: flex; gap: 1vw; padding-left: 5vw; align-items: center;">
        <v-icon size="35" icon="mdi-door-open" color="#00d492"></v-icon>
        <v-toolbar-title text="Face Authentication System"></v-toolbar-title>
      </div>
    </v-toolbar>

    <v-main>
      <div class="main-content-container">
        <RouterView/>
      </div>
    </v-main>
  </v-app>
</template>

<style scoped>
.v-application {
  background-color: #0f172b !important;
}

.main-content-container {
  padding: 5vh;
  height: 100%;
}
</style>
