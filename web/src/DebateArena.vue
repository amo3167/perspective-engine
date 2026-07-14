<template>
  <v-container fluid class="debate-arena pa-6">
    <!-- Header: Topic & Control -->
    <v-row>
      <v-col cols="12">
        <v-card class="elevation-4 rounded-xl overflow-hidden" border>
          <v-progress-linear
            v-if="status === 'debating'"
            indeterminate
            color="primary"
            height="4"
          ></v-progress-linear>
          <v-card-item class="bg-surface-variant py-4">
            <template v-slot:prepend>
              <v-icon icon="mdi-account-group" size="36" color="primary"></v-icon>
            </template>
            <v-card-title class="text-h5 font-weight-bold">
              Multi-Agent Debate Arena
            </v-card-title>
            <v-card-subtitle>
              Real-time strategic analysis through agentic reasoning
            </v-card-subtitle>
            <template v-slot:append>
              <v-chip
                :color="statusColor"
                variant="flat"
                class="text-uppercase font-weight-bold"
              >
                {{ statusText }}
              </v-chip>
            </template>
          </v-card-item>

          <v-divider></v-divider>

          <v-card-text class="pa-6">
            <div class="text-h6 mb-2">Topic:</div>
            <div class="text-h4 font-weight-light text-primary mb-4">
              {{ topic || 'Waiting for topic...' }}
            </div>
            
            <div class="d-flex align-center gap-4">
              <v-btn
                prepend-icon="mdi-play"
                color="primary"
                size="large"
                :loading="status === 'debating'"
                @click="startDebate"
              >
                Start Live Session
              </v-btn>
              <v-btn
                prepend-icon="mdi-history"
                variant="outlined"
                color="secondary"
                size="large"
                @click="clearTranscript"
              >
                Clear Arena
              </v-btn>
              <v-spacer></v-spacer>
              <div v-if="timeRemaining !== null" class="text-h6 text-medium-emphasis">
                <v-icon icon="mdi-clock-outline" class="mr-1"></v-icon>
                {{ formatTime(timeRemaining) }}
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Team Scoreboard -->
    <v-row class="mt-4">
      <v-col cols="12" lg="10" offset-lg="1">
        <v-card class="scoreboard rounded-xl overflow-hidden" variant="outlined">
          <v-row no-gutters align="center">
            <!-- Team PRO -->
            <v-col cols="5" class="pa-4 team-pro-bg">
              <div class="d-flex align-center mb-2">
                <v-icon icon="mdi-sword-cross" color="blue" class="mr-2"></v-icon>
                <span class="text-h6 font-weight-bold text-blue">TEAM PRO</span>
                <v-chip size="x-small" color="blue" variant="tonal" class="ml-2">3 Agents</v-chip>
              </div>
              <div class="d-flex flex-wrap gap-2">
                <v-chip v-for="a in teamProAgents" :key="a.id" :color="a.color" variant="tonal" size="small" :prepend-icon="a.icon">
                  {{ a.name }}
                </v-chip>
              </div>
            </v-col>

            <!-- VS Divider -->
            <v-col cols="2" class="text-center pa-4 vs-section">
              <div class="vs-badge">VS</div>
            </v-col>

            <!-- Team CON -->
            <v-col cols="5" class="pa-4 team-con-bg text-right">
              <div class="d-flex align-center justify-end mb-2">
                <v-chip size="x-small" color="red" variant="tonal" class="mr-2">3 Agents</v-chip>
                <span class="text-h6 font-weight-bold text-red">TEAM CON</span>
                <v-icon icon="mdi-shield-sword" color="red" class="ml-2"></v-icon>
              </div>
              <div class="d-flex flex-wrap justify-end gap-2">
                <v-chip v-for="a in teamConAgents" :key="a.id" :color="a.color" variant="tonal" size="small" :prepend-icon="a.icon">
                  {{ a.name }}
                </v-chip>
              </div>
            </v-col>
          </v-row>
        </v-card>
      </v-col>
    </v-row>

    <!-- Debate Lanes -->
    <v-row class="mt-6">
      <v-col cols="12" lg="10" offset-lg="1">
        <div class="debate-lanes">
          <!-- Center Line -->
          <div class="center-line"></div>

          <!-- Turn Entries -->
          <div
            v-for="(turn, index) in transcript"
            :key="index"
            :class="[
              'lane-entry',
              `lane-${getTeamSide(turn.agent_id)}`,
              { 'lane-entry-animate': true }
            ]"
          >
            <!-- Connector dot on the center line -->
            <div class="lane-dot" :style="{ background: getDotColor(turn.agent_id) }">
              <v-icon :icon="getAgentIcon(turn.agent_id)" size="16" color="white"></v-icon>
            </div>

            <!-- Card -->
            <v-card
              :class="[
                'lane-card elevation-2 rounded-lg',
                `team-border-${getTeamSide(turn.agent_id)}`,
                { 'judge-card': getTeamSide(turn.agent_id) === 'judge' }
              ]"
              border
            >
              <v-card-item class="py-3">
                <template v-slot:prepend>
                  <v-avatar :color="getAgentColor(turn.agent_id)" size="36" class="mr-3">
                    <span class="text-white font-weight-bold text-caption">{{ getAgentInitial(turn.agent_id) }}</span>
                  </v-avatar>
                </template>
                <v-card-title class="text-subtitle-1 font-weight-bold d-flex align-center flex-wrap">
                  {{ formatAgentName(turn.agent_id) }}
                  <v-chip
                    v-if="getTeamSide(turn.agent_id) !== 'judge'"
                    :color="getTeamSide(turn.agent_id) === 'pro' ? 'blue' : 'red'"
                    variant="flat"
                    size="x-small"
                    class="ml-2 font-weight-bold"
                  >
                    {{ getTeamSide(turn.agent_id) === 'pro' ? 'PRO' : 'CON' }}
                  </v-chip>
                  <v-chip
                    v-else
                    color="amber-darken-2"
                    variant="flat"
                    size="x-small"
                    class="ml-2 font-weight-bold"
                  >
                    VERDICT
                  </v-chip>
                </v-card-title>
                <v-card-subtitle class="text-caption">
                  {{ turn.timestamp ? new Date(turn.timestamp).toLocaleTimeString() : '' }}
                </v-card-subtitle>
              </v-card-item>
              
              <v-card-text class="pt-0 pb-4 px-4 text-body-2 line-height-relaxed">
                <div class="markdown-content" v-html="renderMarkdown(turn.content)"></div>
              </v-card-text>
            </v-card>
          </div>

          <!-- Loading state -->
          <div v-if="transcript.length === 0 && status === 'debating'" class="lane-entry lane-judge">
            <div class="lane-dot" style="background: #9E9E9E;">
              <v-icon icon="mdi-loading mdi-spin" size="16" color="white"></v-icon>
            </div>
            <div class="text-subtitle-1 text-medium-emphasis italic lane-card pa-4">
              Agents are gathering in the arena...
            </div>
          </div>
        </div>
      </v-col>
    </v-row>

    <!-- Bottom Action -->
    <v-fab
      v-if="transcript.length > 5"
      icon="mdi-chevron-up"
      location="bottom end"
      class="mb-6 mr-6"
      color="primary"
      @click="scrollToTop"
    ></v-fab>
  </v-container>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import { sanitizeHtml } from './markdown'

// State
const topic = ref('')
const status = ref<'idle' | 'debating' | 'finished'>('idle')
const transcript = ref<any[]>([])
const timeRemaining = ref<number | null>(null)
let timerInterval: ReturnType<typeof setInterval> | null = null

const wsMessage = ref<any>(null)
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

function connectWebSocket(): void {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${window.location.host}/ws`)
  ws.onmessage = (event) => {
    try {
      wsMessage.value = JSON.parse(event.data)
    } catch { /* ignore */ }
  }
  ws.onclose = () => {
    reconnectTimer = setTimeout(connectWebSocket, 3000)
  }
  ws.onerror = () => ws?.close()
}

onMounted(() => connectWebSocket())
onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws?.close()
})

// Computed
const statusText = computed(() => {
  if (status.value === 'debating') return 'Live Debating'
  if (status.value === 'finished') return 'Completed'
  return 'Ready'
})

const statusColor = computed(() => {
  if (status.value === 'debating') return 'success'
  if (status.value === 'finished') return 'primary'
  return 'grey'
})

// Team roster data for scoreboard
const teamProAgents = [
  { id: 'A1', name: 'Forecaster', color: 'blue', icon: 'mdi-crystal-ball' },
  { id: 'A2', name: 'Innovator', color: 'indigo', icon: 'mdi-lightbulb-on' },
  { id: 'A3', name: 'Economist', color: 'light-blue', icon: 'mdi-chart-line' }
]
const teamConAgents = [
  { id: 'B1', name: 'Regulator', color: 'red', icon: 'mdi-shield-check' },
  { id: 'B2', name: 'Ethicist', color: 'deep-orange', icon: 'mdi-scale-balance' },
  { id: 'B3', name: 'Traditionalist', color: 'pink', icon: 'mdi-bank' }
]

watch(wsMessage, (msg: any) => {
  if (!msg || msg.type !== 'debate_update') return
  
  const dType = msg.debate_type || msg.type

  if (dType === 'debate_start') {
    status.value = 'debating'
    topic.value = msg.topic
    transcript.value = []
    startTimer(msg.time_limit_seconds || 180) 
  } else if (dType === 'debate_turn') {
    const alreadyExists = transcript.value.some(t => 
      t.agent_id === msg.agent_id && t.turn_index === msg.turn_index
    )
    
    if (!alreadyExists) {
      transcript.value.push({
        agent_id: msg.agent_id,
        content: msg.content,
        timestamp: msg.timestamp,
        turn_index: msg.turn_index
      })
      scrollToLatest()
    }
  } else if (dType === 'debate_finish') {
    status.value = 'finished'
    stopTimer()
  }
})

// Team & Agent Helpers
const getTeamSide = (id: string): 'pro' | 'con' | 'judge' => {
  if (id.startsWith('A')) return 'pro'
  if (id.startsWith('B')) return 'con'
  return 'judge'
}

const getAgentInitial = (id: string): string => {
  if (id === 'J_Justice') return 'J'
  return id.substring(0, 2)
}

const formatAgentName = (id: string) => {
  const map: Record<string, string> = {
    'J_Justice': 'The Judge of Justice',
    'A1_Forecaster': 'Master Forecaster',
    'A2_Innovator': 'Creative Innovator',
    'A3_Economist': 'Technical Economist',
    'B1_Regulator': 'Strategic Regulator',
    'B2_Ethicist': 'Social Ethicist',
    'B3_Traditionalist': 'Institutional Traditionalist'
  }
  return map[id] || id
}

const getAgentColor = (id: string) => {
  const map: Record<string, string> = {
    'A1_Forecaster': 'blue',
    'A2_Innovator': 'indigo',
    'A3_Economist': 'light-blue',
    'B1_Regulator': 'red-darken-1',
    'B2_Ethicist': 'deep-orange',
    'B3_Traditionalist': 'pink',
    'J_Justice': 'amber-darken-2'
  }
  return map[id] || 'grey'
}

const getDotColor = (id: string) => {
  const map: Record<string, string> = {
    'A1_Forecaster': '#2196F3',
    'A2_Innovator': '#3F51B5',
    'A3_Economist': '#03A9F4',
    'B1_Regulator': '#E53935',
    'B2_Ethicist': '#FF5722',
    'B3_Traditionalist': '#E91E63',
    'J_Justice': '#FFA000'
  }
  return map[id] || '#9E9E9E'
}

const getAgentIcon = (id: string) => {
  const map: Record<string, string> = {
    'J_Justice': 'mdi-gavel',
    'A1_Forecaster': 'mdi-crystal-ball',
    'A2_Innovator': 'mdi-lightbulb-on',
    'A3_Economist': 'mdi-chart-line',
    'B1_Regulator': 'mdi-shield-check',
    'B2_Ethicist': 'mdi-scale-balance',
    'B3_Traditionalist': 'mdi-bank'
  }
  return map[id] || 'mdi-account'
}

const renderMarkdown = (text: string) => {
  return sanitizeHtml(marked(text) as string)
}

const formatTime = (seconds: number) => {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

// Actions
const startDebate = async () => {
  try {
    status.value = 'debating'
    const res = await fetch('/api/monitor/debate/start', { method: 'POST' })
    if (!res.ok) throw new Error(await res.text())
  } catch (err) {
    console.error('Failed to start debate via API:', err)
    status.value = 'idle'
  }
}

const clearTranscript = () => {
  transcript.value = []
  topic.value = ''
  status.value = 'idle'
  stopTimer()
}

const startTimer = (limit: number) => {
  stopTimer()
  timeRemaining.value = limit
  timerInterval = setInterval(() => {
    if (timeRemaining.value && timeRemaining.value > 0) {
      timeRemaining.value--
    } else {
      stopTimer()
    }
  }, 1000)
}

const stopTimer = () => {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
  timeRemaining.value = null
}

const scrollToLatest = () => {
  setTimeout(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  }, 100)
}

const scrollToTop = () => {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const fetchCurrentState = async () => {
  try {
    const res = await fetch('/api/monitor/debate/current')
    const data = await res.json()
    if (data && data.topic) {
      topic.value = data.topic
      status.value = data.status === 'active' ? 'debating' : 'finished'

      if (data.turns && data.turns.length > 0) {
        const existingTimestamps = new Set(transcript.value.map(t => t.timestamp))
        const historicalTurns = data.turns.filter((t: any) => !existingTimestamps.has(t.timestamp))
        transcript.value = [...transcript.value, ...historicalTurns].sort((a, b) =>
          new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
        )
      }
    }
  } catch (err) {
    console.error('Failed to fetch debate state:', err)
  }
}

onMounted(async () => {
  await fetchCurrentState()
})
</script>

<style scoped>
.debate-arena {
  max-width: 1400px;
  margin: 0 auto;
}

.line-height-relaxed {
  line-height: 1.625;
}

/* ── Scoreboard ── */
.scoreboard {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.team-pro-bg {
  background: linear-gradient(135deg, rgba(33, 150, 243, 0.06) 0%, transparent 100%);
  border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.team-con-bg {
  background: linear-gradient(225deg, rgba(244, 67, 54, 0.06) 0%, transparent 100%);
  border-left: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.vs-section {
  position: relative;
}

.vs-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: rgba(var(--v-theme-surface-variant), 1);
  border: 2px solid rgba(var(--v-border-color), 0.3);
  font-weight: 900;
  font-size: 1rem;
  letter-spacing: 0.05em;
  color: rgba(var(--v-theme-on-surface), 0.7);
}

/* ── Split-Lane Layout ── */
.debate-lanes {
  position: relative;
  min-height: 100px;
  padding: 1rem 0;
}

.center-line {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  background: linear-gradient(
    to bottom,
    transparent 0%,
    rgba(var(--v-border-color), 0.3) 5%,
    rgba(var(--v-border-color), 0.3) 95%,
    transparent 100%
  );
  transform: translateX(-50%);
  z-index: 0;
}

/* Each lane entry */
.lane-entry {
  position: relative;
  display: flex;
  align-items: flex-start;
  margin-bottom: 1.5rem;
  animation: fadeSlideIn 0.4s ease-out;
}

/* PRO entries: card on the LEFT, dot in center */
.lane-pro {
  justify-content: flex-start;
  padding-right: calc(50% + 24px);
}

.lane-pro .lane-dot {
  position: absolute;
  left: 50%;
  top: 18px;
  transform: translateX(-50%);
}

.lane-pro .lane-card {
  width: 100%;
}

/* CON entries: card on the RIGHT, dot in center */
.lane-con {
  justify-content: flex-end;
  padding-left: calc(50% + 24px);
}

.lane-con .lane-dot {
  position: absolute;
  left: 50%;
  top: 18px;
  transform: translateX(-50%);
}

.lane-con .lane-card {
  width: 100%;
}

/* JUDGE: full width, centered */
.lane-judge {
  justify-content: center;
  padding: 0 4rem;
}

.lane-judge .lane-dot {
  position: absolute;
  left: 50%;
  top: 18px;
  transform: translateX(-50%);
  z-index: 2;
}

.lane-judge .lane-card {
  width: 100%;
  margin-top: 0;
}

/* Connector dot */
.lane-dot {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
  flex-shrink: 0;
  box-shadow: 0 0 0 4px rgba(var(--v-theme-surface), 1), 0 2px 8px rgba(0, 0, 0, 0.3);
}

/* Turn card team borders and elevation */
.lane-card {
  position: relative;
  z-index: 1; /* Content above the center line */
  background: rgb(var(--v-theme-surface)) !important;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.team-border-pro {
  border-left: 4px solid #2196F3 !important;
}

.team-border-con {
  border-left: 4px solid #F44336 !important;
}

.team-border-judge {
  border-left: 4px solid #FFC107 !important;
}

/* Judge card distinct solid styling */
.judge-card {
  z-index: 2; /* Higher priority */
  background: #1a1a1a !important; /* Deep solid background to mask the line */
  border: 1px solid rgba(255, 193, 7, 0.4) !important;
  border-left: 6px solid #FFC107 !important;
  box-shadow: 0 4px 20px rgba(255, 193, 7, 0.1) !important;
}

/* Markdown content */
.markdown-content :deep(p) {
  margin-bottom: 0.75rem;
}

.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(strong) {
  color: rgb(var(--v-theme-primary));
}

.markdown-content :deep(ul), .markdown-content :deep(ol) {
  margin-left: 1.5rem;
  margin-bottom: 0.75rem;
}

/* Animation */
@keyframes fadeSlideIn {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.gap-4 {
  gap: 1rem;
}

.gap-2 {
  gap: 0.5rem;
}

/* Mobile responsive: stack to single column */
@media (max-width: 960px) {
  .lane-pro,
  .lane-con {
    padding-left: 44px;
    padding-right: 0;
    justify-content: flex-start;
  }

  .lane-pro .lane-dot,
  .lane-con .lane-dot {
    left: 0;
    transform: translateX(0);
  }

  .lane-judge {
    padding: 0;
    padding-left: 44px;
  }

  .lane-judge .lane-dot {
    left: 0;
    transform: translateX(0);
  }

  .center-line {
    left: 16px;
  }
}
</style>
