<template>
  <v-app>
    <v-app-bar color="surface" flat border="b" density="comfortable">
      <v-toolbar-title class="text-subtitle-1 font-weight-bold">
        Perspective Engine
      </v-toolbar-title>
      <v-spacer />
      <v-btn variant="text" to="/" exact>
        Meeting
      </v-btn>
      <v-btn variant="text" to="/debate">
        Debate Arena
      </v-btn>
      <v-btn variant="text" to="/research">
        Research Lab
      </v-btn>
    </v-app-bar>
    <v-main>
      <router-view />
    </v-main>
  </v-app>
</template>

<script setup lang="ts">
</script>
