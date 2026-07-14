<template>
  <v-container fluid class="research-lab pa-6">
    <!-- Header: Config Panel -->
    <v-row>
      <v-col cols="12">
        <v-card class="elevation-4 rounded-xl overflow-hidden" border>
          <v-progress-linear
            v-if="status === 'running'"
            indeterminate
            color="teal"
            height="4"
          />
          <v-card-item class="bg-surface-variant py-4">
            <template v-slot:prepend>
              <v-icon icon="mdi-flask" size="36" color="teal" />
            </template>
            <v-card-title class="text-h5 font-weight-bold">
              Research Lab
            </v-card-title>
            <v-card-subtitle>
              Multi-agent customer research pipeline — PO brief, survey, responses, compile, analysis
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

          <v-divider />

          <v-card-text class="pa-6">
            <v-textarea
              v-model="featureText"
              label="Feature Description"
              placeholder="Describe the feature to research with your synthetic customers..."
              variant="outlined"
              rows="4"
              auto-grow
              :disabled="status === 'running'"
              class="mb-4"
            />

            <v-row align="center" class="ga-4">
              <v-col cols="12" sm="3">
                <v-slider
                  v-model="customerCount"
                  :min="5"
                  :max="200"
                  :step="5"
                  label="Customers"
                  thumb-label="always"
                  color="teal"
                  :disabled="status === 'running'"
                />
              </v-col>
              <v-col cols="12" sm="2">
                <v-select
                  v-model="mode"
                  :items="['survey', 'feedback']"
                  label="Mode"
                  variant="outlined"
                  density="compact"
                  :disabled="status === 'running'"
                />
              </v-col>
              <v-col cols="12" sm="2">
                <v-select
                  v-model="backend"
                  :items="['bedrock', 'gemini']"
                  label="Backend"
                  variant="outlined"
                  density="compact"
                  :disabled="status === 'running'"
                />
              </v-col>
              <v-col cols="auto">
                <v-checkbox
                  v-model="agenticMode"
                  label="Agentic"
                  color="teal"
                  density="compact"
                  hide-details
                  :disabled="status === 'running'"
                />
              </v-col>
              <v-col cols="auto">
                <v-checkbox
                  v-model="dryRun"
                  label="Dry Run"
                  color="grey"
                  density="compact"
                  hide-details
                  :disabled="status === 'running'"
                />
              </v-col>
              <v-spacer />
              <v-col cols="auto" class="d-flex ga-3 align-center">
                <v-btn
                  prepend-icon="mdi-rocket-launch"
                  color="teal"
                  size="large"
                  :loading="status === 'running'"
                  :disabled="!featureText.trim()"
                  @click="handleLaunch"
                >
                  Launch Research
                </v-btn>
                <v-btn
                  prepend-icon="mdi-history"
                  variant="outlined"
                  size="large"
                  @click="historyDrawer = true"
                >
                  History
                </v-btn>
                <div v-if="elapsedText" class="text-subtitle-1 text-medium-emphasis ml-2">
                  <v-icon icon="mdi-clock-outline" size="18" class="mr-1" />
                  {{ elapsedText }}
                </div>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Pipeline Stepper -->
    <v-row class="mt-4">
      <v-col cols="12">
        <v-card class="rounded-xl overflow-hidden" variant="outlined">
          <div class="pipeline-stepper pa-4">
            <div
              v-for="step in pipelineSteps"
              :key="step.step"
              :class="['step-item', stepStatusClass(step.step)]"
            >
              <v-avatar
                :color="getAgentColor(step.agent)"
                size="44"
                class="step-avatar"
              >
                <v-icon :icon="getAgentIcon(step.agent)" size="22" color="white" />
              </v-avatar>
              <div class="step-label">{{ step.label }}</div>
              <div class="step-agent text-caption text-medium-emphasis">{{ step.agentLabel }}</div>
              <div v-if="completedStepDurations[step.step]" class="step-duration text-caption">
                {{ formatDuration(completedStepDurations[step.step]) }}
              </div>
              <v-icon
                v-if="stepState(step.step) === 'done'"
                icon="mdi-check-circle"
                color="success"
                size="18"
                class="step-status-icon"
              />
              <v-progress-circular
                v-else-if="stepState(step.step) === 'active'"
                indeterminate
                :color="getAgentColor(step.agent)"
                size="18"
                width="2"
                class="step-status-icon"
              />
              <v-icon
                v-else
                icon="mdi-circle-outline"
                color="grey-lighten-1"
                size="18"
                class="step-status-icon"
              />
              <div
                v-if="step.step < 5"
                :class="['step-connector', { 'connector-done': stepState(step.step) === 'done' }]"
              />
            </div>
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Live Activity Feed -->
    <v-row class="mt-4" v-if="activityFeed.length > 0">
      <v-col cols="12">
        <v-card class="rounded-xl overflow-hidden" variant="outlined">
          <v-card-item class="py-3 px-4 bg-surface-variant">
            <template v-slot:prepend>
              <v-icon icon="mdi-pulse" color="teal" />
            </template>
            <v-card-title class="text-subtitle-1 font-weight-bold">Live Activity</v-card-title>
            <template v-slot:append>
              <v-chip size="small" color="teal" variant="tonal">
                {{ activityFeed.length }} events
              </v-chip>
            </template>
          </v-card-item>
          <v-divider />
          <div class="activity-feed pa-4" ref="feedContainer">
            <div
              v-for="(event, idx) in activityFeed"
              :key="idx"
              :class="['feed-entry', `agent-${event.agent}`]"
            >
              <v-avatar :color="getAgentColor(event.agent)" size="28" class="mr-3 flex-shrink-0">
                <v-icon :icon="getAgentIcon(event.agent)" size="14" color="white" />
              </v-avatar>
              <div class="feed-content">
                <span class="font-weight-medium" :style="{ color: getAgentHex(event.agent) }">
                  {{ getAgentLabel(event.agent) }}
                </span>
                <span class="text-body-2 ml-2">{{ event.message }}</span>
                <v-chip
                  v-if="event.artifact"
                  size="x-small"
                  color="teal"
                  variant="tonal"
                  class="ml-2"
                  @click="handleViewArtifact(event.artifact)"
                >
                  {{ event.artifact }}
                </v-chip>
              </div>
              <span class="text-caption text-medium-emphasis ml-auto flex-shrink-0">
                {{ event.time }}
              </span>
            </div>
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Artifact Viewer -->
    <v-row class="mt-4" v-if="hasArtifacts">
      <v-col cols="12">
        <v-card class="rounded-xl overflow-hidden" variant="outlined">
          <v-tabs v-model="activeArtifactTab" color="teal" slider-color="teal">
            <v-tab
              v-for="tab in artifactTabs"
              :key="tab.key"
              :value="tab.key"
            >
              <v-icon :icon="tab.icon" size="18" class="mr-2" />
              {{ tab.label }}
              <v-chip
                v-if="tab.isNew"
                size="x-small"
                color="teal"
                variant="flat"
                class="ml-2"
              >
                NEW
              </v-chip>
            </v-tab>
          </v-tabs>
          <v-divider />
          <v-card-text class="pa-6 artifact-content">
            <div v-if="activeArtifactContent === null" class="text-center text-medium-emphasis pa-8">
              <v-icon icon="mdi-file-document-outline" size="48" class="mb-2" />
              <div>Waiting for artifacts...</div>
            </div>

            <div v-else-if="activeArtifactTab === 'survey'" class="survey-viewer">
              <template v-if="surveyDoc">
                <div class="text-h6 mb-3">{{ surveyDoc.title }}</div>
                <div class="text-body-2 text-medium-emphasis mb-4">{{ surveyDoc.intro }}</div>
                <v-card
                  v-for="(q, qi) in (surveyDoc.questions || [])"
                  :key="qi"
                  variant="tonal"
                  class="mb-3 pa-4"
                >
                  <div class="d-flex align-center ga-2 mb-2">
                    <v-chip size="x-small" :color="questionTypeColor(q.type || '')" variant="flat">
                      {{ q.type }}
                    </v-chip>
                    <span class="font-weight-medium">{{ q.text }}</span>
                  </div>
                  <div v-if="q.options" class="text-caption text-medium-emphasis">
                    Options: {{ q.options.join(', ') }}
                  </div>
                  <div v-if="q.scale_min != null" class="text-caption text-medium-emphasis">
                    Scale: {{ q.scale_min }}–{{ q.scale_max }}
                    <template v-if="q.scale_labels">({{ q.scale_labels.join(' → ') }})</template>
                  </div>
                </v-card>
              </template>
              <div v-else class="markdown-content" v-html="renderMarkdown(String(activeArtifactContent))" />
            </div>

            <div v-else-if="activeArtifactTab === 'responses'" class="responses-viewer">
              <template v-if="responsesList">
                <div class="text-subtitle-1 mb-3">
                  {{ responsesList.length }} responses collected
                </div>
                <v-expansion-panels variant="accordion">
                  <v-expansion-panel
                    v-for="(resp, ri) in responsesList.slice(0, responsesDisplayLimit)"
                    :key="ri"
                  >
                    <v-expansion-panel-title>
                      <v-avatar color="blue-grey" size="24" class="mr-2">
                        <span class="text-caption text-white">{{ ri + 1 }}</span>
                      </v-avatar>
                      {{ resp.archetype_label || resp.persona_id || `Persona ${ri + 1}` }}
                    </v-expansion-panel-title>
                    <v-expansion-panel-text>
                      <pre class="text-caption" style="white-space: pre-wrap;">{{ JSON.stringify(resp.answers || resp, null, 2) }}</pre>
                    </v-expansion-panel-text>
                  </v-expansion-panel>
                </v-expansion-panels>
                <div v-if="responsesList.length > responsesDisplayLimit" class="d-flex align-center mt-3 gap-2">
                  <span class="text-caption text-medium-emphasis">
                    Showing {{ Math.min(responsesDisplayLimit, responsesList.length) }} of {{ responsesList.length }} responses
                  </span>
                  <v-btn
                    size="small"
                    variant="text"
                    @click="responsesDisplayLimit = responsesList.length"
                  >
                    Show All
                  </v-btn>
                </div>
              </template>
              <div v-else class="markdown-content" v-html="renderMarkdown(String(activeArtifactContent))" />
            </div>

            <div v-else class="markdown-content" v-html="renderMarkdown(String(activeArtifactContent))" />
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Run History Drawer -->
    <v-navigation-drawer
      v-model="historyDrawer"
      location="right"
      temporary
      width="380"
    >
      <v-list-item class="py-4 px-4">
        <template v-slot:prepend>
          <v-icon icon="mdi-history" color="teal" />
        </template>
        <v-list-item-title class="font-weight-bold">Run History</v-list-item-title>
        <template v-slot:append>
          <v-btn icon="mdi-close" variant="text" size="small" @click="historyDrawer = false" />
        </template>
      </v-list-item>
      <v-divider />
      <div v-if="runHistoryLoading" class="pa-8 text-center">
        <v-progress-circular indeterminate color="teal" />
      </div>
      <v-list v-else-if="runHistory.length > 0" density="compact">
        <v-list-item
          v-for="run in runHistory"
          :key="run.id"
          @click="handleLoadRun(run)"
          :active="activeRunId === run.id"
          active-color="teal"
          class="mb-1"
        >
          <template v-slot:prepend>
            <v-icon
              :icon="run.completed ? 'mdi-check-circle' : 'mdi-circle-outline'"
              :color="run.completed ? 'success' : 'grey'"
              size="18"
            />
          </template>
          <v-list-item-title class="text-body-2 font-weight-medium">
            {{ formatRunTimestamp(run.timestamp) }}
          </v-list-item-title>
          <v-list-item-subtitle class="text-caption">
            {{ run.count }} respondents · {{ run.artifacts.length }} files
          </v-list-item-subtitle>
          <template v-slot:append>
            <v-btn
              icon="mdi-delete-outline"
              size="x-small"
              variant="text"
              color="error"
              @click.stop="handleDeleteRun(run.id)"
            />
          </template>
        </v-list-item>
      </v-list>
      <div v-else class="pa-8 text-center text-medium-emphasis">
        <v-icon icon="mdi-folder-open-outline" size="48" class="mb-2" />
        <div>No runs yet</div>
      </div>
    </v-navigation-drawer>
  </v-container>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { marked } from 'marked'
import { sanitizeHtml } from './markdown'

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

interface FeedbackEvent {
  feedback_type: string
  run_id?: string
  step?: number
  agent?: string
  message?: string
  artifact?: string
  count?: number
  total?: number
  elapsed_ms?: number
  [key: string]: unknown
}

interface ActivityEntry {
  agent: string
  message: string
  artifact?: string
  time: string
}

interface RunInfo {
  id: string
  timestamp: string
  artifacts: string[]
  count: number | string
  mode: string
  completed: boolean
}

const PIPELINE_STEPS = [
  { step: 1, label: 'PO Brief', agent: 'product_owner', agentLabel: 'Product Owner' },
  { step: 2, label: 'Survey Design', agent: 'marketing_researcher', agentLabel: 'Marketing' },
  { step: 3, label: 'Customer Responses', agent: 'customers', agentLabel: 'Customers' },
  { step: 4, label: 'Compile Findings', agent: 'marketing_researcher', agentLabel: 'Marketing' },
  { step: 5, label: 'PO Analysis', agent: 'product_owner', agentLabel: 'Product Owner' },
] as const

const AGENT_COLORS: Record<string, string> = {
  product_owner: 'amber-darken-2',
  marketing_researcher: 'teal',
  customers: 'blue-grey',
}

const AGENT_HEX: Record<string, string> = {
  product_owner: '#FFA000',
  marketing_researcher: '#00897B',
  customers: '#546E7A',
}

const AGENT_ICONS: Record<string, string> = {
  product_owner: 'mdi-crown',
  marketing_researcher: 'mdi-chart-box',
  customers: 'mdi-account-group',
}

const AGENT_LABELS: Record<string, string> = {
  product_owner: 'Product Owner',
  marketing_researcher: 'Marketing Researcher',
  customers: 'Customers',
}

const ARTIFACT_MAP: Record<string, { key: string; label: string; icon: string }> = {
  'research_brief.md': { key: 'brief', label: 'Research Brief', icon: 'mdi-file-document' },
  'survey.json': { key: 'survey', label: 'Survey', icon: 'mdi-clipboard-list' },
  'survey_responses.json': { key: 'responses', label: 'Responses', icon: 'mdi-account-group' },
  'marketing_report.md': { key: 'marketing', label: 'Marketing Report', icon: 'mdi-chart-box' },
  'po_analysis.md': { key: 'analysis', label: 'PO Analysis', icon: 'mdi-crown' },
}

const featureText = ref(
  `**New Feature: Portfolio Performance Dashboard**

We're adding a real-time portfolio performance dashboard to AutoBBS. Key capabilities:

- **Live P&L tracking** across all active strategies, updated every 30 seconds
- **Drawdown alerts** with customizable thresholds (email + in-app notification)
- **Historical equity curve** visualization with interactive zoom (1D, 1W, 1M, 3M, 1Y views)
- **Export to CSV/PDF** for tax reporting and record-keeping
- **Mobile-responsive design** — full functionality on phone and tablet
- **Strategy comparison** — overlay multiple strategies on the same chart
- **Risk metrics panel** — Sharpe ratio, max drawdown, win rate, profit factor at a glance`
)
const customerCount = ref(20)
const mode = ref('survey')
const backend = ref('bedrock')
const agenticMode = ref(true)
const dryRun = ref(false)

const status = ref<'idle' | 'running' | 'complete' | 'error'>('idle')
const currentStep = ref(0)
const completedSteps = ref<Set<number>>(new Set())
const completedStepDurations = ref<Record<number, number>>({})
const activeRunId = ref<string | null>(null)

const activityFeed = ref<ActivityEntry[]>([])
const feedContainer = ref<HTMLElement | null>(null)

const artifacts = ref<Record<string, { content: unknown; isNew: boolean }>>({})
const responsesDisplayLimit = ref(30)
const activeArtifactTab = ref<string>('brief')

const historyDrawer = ref(false)
const runHistory = ref<RunInfo[]>([])
const runHistoryLoading = ref(false)

const elapsedMs = ref(0)
let elapsedInterval: ReturnType<typeof setInterval> | null = null

const pipelineSteps = PIPELINE_STEPS

const statusText = computed(() => {
  if (status.value === 'running') return 'Running'
  if (status.value === 'complete') return 'Complete'
  if (status.value === 'error') return 'Error'
  return 'Ready'
})

const statusColor = computed(() => {
  if (status.value === 'running') return 'success'
  if (status.value === 'complete') return 'teal'
  if (status.value === 'error') return 'error'
  return 'grey'
})

const elapsedText = computed(() => {
  if (elapsedMs.value === 0 && status.value === 'idle') return ''
  return formatDuration(elapsedMs.value)
})

const hasArtifacts = computed(() => Object.keys(artifacts.value).length > 0)

const artifactTabs = computed(() => {
  const tabs: { key: string; label: string; icon: string; isNew: boolean }[] = []
  for (const [filename, meta] of Object.entries(ARTIFACT_MAP)) {
    const entry = artifacts.value[meta.key]
    if (entry) {
      tabs.push({ ...meta, isNew: entry.isNew })
    }
  }
  return tabs
})

const activeArtifactContent = computed(() => {
  const entry = artifacts.value[activeArtifactTab.value]
  return entry ? entry.content : null
})

type SurveyQuestion = {
  type?: string
  text?: string
  options?: string[]
  scale_min?: number
  scale_max?: number
  scale_labels?: string[]
}

type SurveyDoc = { title?: string; intro?: string; questions?: SurveyQuestion[] }

const surveyDoc = computed((): SurveyDoc | null => {
  const c = activeArtifactContent.value
  if (c && typeof c === 'object' && !Array.isArray(c)) return c as SurveyDoc
  return null
})

const responsesList = computed((): Record<string, unknown>[] | null => {
  const c = activeArtifactContent.value
  return Array.isArray(c) ? (c as Record<string, unknown>[]) : null
})

const getAgentColor = (agent: string) => AGENT_COLORS[agent] || 'grey'
const getAgentHex = (agent: string) => AGENT_HEX[agent] || '#9E9E9E'
const getAgentIcon = (agent: string) => AGENT_ICONS[agent] || 'mdi-account'
const getAgentLabel = (agent: string) => AGENT_LABELS[agent] || agent

const stepState = (step: number): 'done' | 'active' | 'pending' => {
  if (completedSteps.value.has(step)) return 'done'
  if (currentStep.value === step && status.value === 'running') return 'active'
  return 'pending'
}

const stepStatusClass = (step: number) => {
  const state = stepState(step)
  return `step-${state}`
}

const questionTypeColor = (type: string) => {
  if (type === 'rating') return 'amber'
  if (type === 'multiple_choice') return 'blue'
  return 'teal'
}

const renderMarkdown = (text: string) => sanitizeHtml(marked(text) as string)

const formatDuration = (ms: number) => {
  const totalSeconds = Math.floor(ms / 1000)
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

const formatRunTimestamp = (ts: string) => {
  if (ts.length >= 15) {
    const y = ts.slice(0, 4)
    const mo = ts.slice(4, 6)
    const d = ts.slice(6, 8)
    const h = ts.slice(9, 11)
    const mi = ts.slice(11, 13)
    return `${y}-${mo}-${d} ${h}:${mi}`
  }
  return ts
}

const addFeedEntry = (agent: string, message: string, artifact?: string) => {
  const now = new Date()
  const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`
  activityFeed.value.push({ agent, message, artifact, time })
  nextTick(() => {
    if (feedContainer.value) {
      feedContainer.value.scrollTop = feedContainer.value.scrollHeight
    }
  })
}

const startElapsedTimer = () => {
  stopElapsedTimer()
  elapsedMs.value = 0
  const t0 = Date.now()
  elapsedInterval = setInterval(() => {
    elapsedMs.value = Date.now() - t0
  }, 1000)
}

const stopElapsedTimer = () => {
  if (elapsedInterval) {
    clearInterval(elapsedInterval)
    elapsedInterval = null
  }
}

watch(wsMessage, (msg: any) => {
  if (!msg || msg.type !== 'feedback_update') return
  const ev = msg as FeedbackEvent

  if (ev.feedback_type === 'pipeline_start') {
    status.value = 'running'
    currentStep.value = 0
    completedSteps.value = new Set()
    completedStepDurations.value = {}
    artifacts.value = {}
    activeRunId.value = ev.run_id || null
    startElapsedTimer()
    addFeedEntry('product_owner', 'Research pipeline started')
  } else if (ev.feedback_type === 'step_start') {
    currentStep.value = ev.step || 0
    addFeedEntry(ev.agent || 'product_owner', ev.message || `Step ${ev.step} started`)
  } else if (ev.feedback_type === 'step_progress') {
    addFeedEntry(
      ev.agent || 'customers',
      ev.message || `Progress: ${ev.count}/${ev.total}`
    )
  } else if (ev.feedback_type === 'step_complete') {
    const step = ev.step || 0
    completedSteps.value.add(step)
    if (ev.elapsed_ms) {
      completedStepDurations.value[step] = ev.elapsed_ms
    }
    const artifactName = ev.artifact || ''
    addFeedEntry(
      ev.agent || 'product_owner',
      `Step ${step} complete`,
      artifactName
    )
    if (artifactName && activeRunId.value) {
      loadArtifact(activeRunId.value, artifactName)
    }
  } else if (ev.feedback_type === 'pipeline_complete') {
    status.value = 'complete'
    stopElapsedTimer()
    if (ev.elapsed_ms) {
      elapsedMs.value = ev.elapsed_ms
    }
    addFeedEntry('product_owner', 'Pipeline complete — all artifacts ready')
  } else if (ev.feedback_type === 'error') {
    status.value = 'error'
    stopElapsedTimer()
    addFeedEntry('product_owner', `Error: ${ev.message}`)
  }
})

const handleLaunch = async () => {
  try {
    status.value = 'running'
    activityFeed.value = []
    currentStep.value = 0
    completedSteps.value = new Set()
    completedStepDurations.value = {}
    artifacts.value = {}
    startElapsedTimer()

    const res = await fetch('/api/feedback-simulator/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feature_text: featureText.value,
        count: customerCount.value,
        mode: mode.value,
        backend: backend.value,
        agentic: agenticMode.value,
        dry_run: dryRun.value,
      }),
    })
    if (!res.ok) throw new Error(await res.text())
  } catch (err) {
    console.error('Failed to launch research:', err)
    status.value = 'error'
    stopElapsedTimer()
    addFeedEntry('product_owner', 'Failed to launch pipeline')
  }
}

const loadArtifact = async (runId: string, filename: string) => {
  const meta = ARTIFACT_MAP[filename]
  if (!meta) return

  try {
    const res = await fetch(`/api/feedback-simulator/runs/${runId}/artifact/${filename}`)
    const data = await res.json()
    if (!res.ok) throw new Error('artifact fetch failed')
    artifacts.value[meta.key] = { content: data.content, isNew: true }
    activeArtifactTab.value = meta.key
    responsesDisplayLimit.value = 30

    setTimeout(() => {
      const entry = artifacts.value[meta.key]
      if (entry) entry.isNew = false
    }, 5000)
  } catch (err) {
    console.error(`Failed to load artifact ${filename}:`, err)
  }
}

const handleViewArtifact = (filename: string) => {
  const meta = ARTIFACT_MAP[filename]
  if (meta && artifacts.value[meta.key]) {
    activeArtifactTab.value = meta.key
  }
}

const fetchRunHistory = async () => {
  runHistoryLoading.value = true
  try {
    const res = await fetch('/api/feedback-simulator/runs')
    runHistory.value = await res.json()
  } catch (err) {
    console.error('Failed to fetch run history:', err)
  } finally {
    runHistoryLoading.value = false
  }
}

const handleLoadRun = async (run: RunInfo) => {
  activeRunId.value = run.id
  status.value = run.completed ? 'complete' : 'idle'
  currentStep.value = 0
  completedSteps.value = new Set()
  completedStepDurations.value = {}
  artifacts.value = {}
  activityFeed.value = []
  stopElapsedTimer()

  for (const filename of run.artifacts) {
    const meta = ARTIFACT_MAP[filename]
    if (!meta) continue

    const stepInfo = PIPELINE_STEPS.find(
      (s) =>
        (filename === 'research_brief.md' && s.step === 1) ||
        (filename === 'survey.json' && s.step === 2) ||
        (filename === 'survey_responses.json' && s.step === 3) ||
        (filename === 'marketing_report.md' && s.step === 4) ||
        (filename === 'po_analysis.md' && s.step === 5)
    )
    if (stepInfo) {
      completedSteps.value.add(stepInfo.step)
    }

    try {
      const res = await fetch(`/api/feedback-simulator/runs/${run.id}/artifact/${filename}`)
      const data = await res.json()
      if (!res.ok) throw new Error('artifact fetch failed')
      artifacts.value[meta.key] = { content: data.content, isNew: false }
    } catch (err) {
      console.error(`Failed to load ${filename}:`, err)
    }
  }

  historyDrawer.value = false
}

const handleDeleteRun = async (runId: string) => {
  try {
    await fetch(`/api/feedback-simulator/runs/${runId}`, { method: 'DELETE' })
    runHistory.value = runHistory.value.filter((r) => r.id !== runId)
    if (activeRunId.value === runId) {
      activeRunId.value = null
      artifacts.value = {}
      completedSteps.value = new Set()
    }
  } catch (err) {
    console.error('Failed to delete run:', err)
  }
}

const fetchCurrentState = async () => {
  try {
    const res = await fetch('/api/monitor/feedback/current')
    const data = await res.json()
    if (data && data.status === 'running') {
      status.value = 'running'
      activeRunId.value = data.run_id || null
      startElapsedTimer()
      if (data.steps) {
        for (const s of data.steps) {
          completedSteps.value.add(s.step)
          if (s.elapsed_ms) completedStepDurations.value[s.step] = s.elapsed_ms
        }
      }
    }
  } catch {
    // monitor not available, that's fine
  }
}

onMounted(async () => {
  await fetchCurrentState()
})

watch(historyDrawer, (open) => {
  if (open) fetchRunHistory()
})
</script>

<style scoped>
.research-lab {
  max-width: 1400px;
  margin: 0 auto;
}

/* ── Pipeline Stepper ── */
.pipeline-stepper {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 0;
  overflow-x: auto;
}

.step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  min-width: 140px;
  flex: 1;
  padding: 0 8px;
}

.step-avatar {
  transition: box-shadow 0.3s ease, transform 0.3s ease;
}

.step-active .step-avatar {
  box-shadow: 0 0 0 4px rgba(0, 137, 123, 0.3), 0 4px 12px rgba(0, 137, 123, 0.2);
  transform: scale(1.1);
  animation: stepPulse 2s ease-in-out infinite;
}

.step-done .step-avatar {
  opacity: 0.85;
}

.step-pending .step-avatar {
  opacity: 0.4;
}

.step-label {
  font-size: 0.8125rem;
  font-weight: 600;
  margin-top: 8px;
  text-align: center;
}

.step-agent {
  margin-top: 2px;
}

.step-duration {
  margin-top: 2px;
  color: rgba(var(--v-theme-on-surface), 0.5);
}

.step-status-icon {
  margin-top: 6px;
}

.step-connector {
  position: absolute;
  top: 22px;
  left: calc(50% + 30px);
  width: calc(100% - 60px);
  height: 2px;
  background: rgba(var(--v-border-color), 0.25);
  transition: background 0.4s ease;
}

.connector-done {
  background: #00897B;
}

@keyframes stepPulse {
  0%, 100% { box-shadow: 0 0 0 4px rgba(0, 137, 123, 0.3); }
  50% { box-shadow: 0 0 0 8px rgba(0, 137, 123, 0.15); }
}

/* ── Activity Feed ── */
.activity-feed {
  max-height: 320px;
  overflow-y: auto;
}

.feed-entry {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid rgba(var(--v-border-color), 0.08);
  animation: fadeSlideIn 0.3s ease-out;
}

.feed-entry:last-child {
  border-bottom: none;
}

.feed-content {
  flex: 1;
  min-width: 0;
}

/* ── Artifact Viewer ── */
.artifact-content {
  max-height: 600px;
  overflow-y: auto;
}

.markdown-content :deep(h1) {
  font-size: 1.5rem;
  font-weight: 700;
  margin: 1.5rem 0 0.75rem;
  color: rgb(var(--v-theme-on-surface));
}

.markdown-content :deep(h2) {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 1.25rem 0 0.5rem;
  color: rgb(var(--v-theme-on-surface));
}

.markdown-content :deep(h3) {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 1rem 0 0.5rem;
}

.markdown-content :deep(p) {
  margin-bottom: 0.75rem;
  line-height: 1.65;
}

.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(strong) {
  color: rgb(var(--v-theme-primary));
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-left: 1.5rem;
  margin-bottom: 0.75rem;
}

.markdown-content :deep(li) {
  margin-bottom: 0.25rem;
}

.markdown-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid rgba(var(--v-border-color), 0.3);
  padding: 8px 12px;
  text-align: left;
}

.markdown-content :deep(th) {
  background: rgba(var(--v-theme-surface-variant), 0.5);
  font-weight: 600;
}

.markdown-content :deep(blockquote) {
  border-left: 3px solid #00897B;
  padding-left: 1rem;
  margin: 0.75rem 0;
  color: rgba(var(--v-theme-on-surface), 0.7);
}

.markdown-content :deep(code) {
  background: rgba(var(--v-theme-surface-variant), 0.6);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.875em;
}

.markdown-content :deep(pre) {
  background: rgba(var(--v-theme-surface-variant), 0.4);
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.75rem 0;
}

/* ── Animations ── */
@keyframes fadeSlideIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ── Mobile ── */
@media (max-width: 960px) {
  .pipeline-stepper {
    gap: 4px;
  }

  .step-item {
    min-width: 80px;
  }

  .step-connector {
    left: calc(50% + 24px);
    width: calc(100% - 48px);
  }
}
</style>
