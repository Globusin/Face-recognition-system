<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <v-app>
    <v-toolbar floating :border="true">
      <div style="display: flex; gap: 1vw; padding-left: 5vw; align-items: center;">
        <v-icon size="35" icon="mdi-door-open"></v-icon>
        <v-img src="@/assets/house_grandpa.jpeg"></v-img>

        <div style="display: flex; flex-direction: column;">
          <v-toolbar-title>Домовой</v-toolbar-title>
          <span class="text-caption" style="font-size: 0.8rem; color: grey;">Система доступа</span>
        </div>
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
.main-content-container {
  padding: 5vh;
  height: 100%;
}
</style>
