import { createRouter, createWebHistory } from 'vue-router'
import MeetingArena from './MeetingArena.vue'
import DebateArena from './DebateArena.vue'
import ResearchLab from './ResearchLab.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'meeting', component: MeetingArena },
    { path: '/debate', name: 'debate', component: DebateArena },
    { path: '/research', name: 'research', component: ResearchLab },
  ],
})
