<template>
  <v-container fluid class="meeting-arena pa-4 pa-md-6">
    <!-- Phase Progress Bar -->
    <v-row class="mb-2">
      <v-col cols="12">
        <div class="phase-tracker">
          <div
            v-for="(phase, idx) in phases"
            :key="phase.id"
            class="phase-step"
            :class="{
              'phase-active': currentPhase === phase.id,
              'phase-done': currentPhase > phase.id,
              'phase-pending': currentPhase < phase.id,
            }"
          >
            <div class="phase-number">{{ idx + 1 }}</div>
            <div class="phase-label">{{ phase.label }}</div>
            <v-icon
              v-if="currentPhase > phase.id"
              icon="mdi-check-circle"
              size="16"
              class="phase-check"
            />
          </div>
        </div>
      </v-col>
    </v-row>

    <!-- Header Card -->
    <v-row>
      <v-col cols="12">
        <v-card class="header-card rounded-lg" variant="flat">
          <v-progress-linear
            v-if="status === 'active'"
            indeterminate
            color="amber-darken-2"
            height="3"
          />
          <div class="header-inner pa-5">
            <div class="d-flex align-center justify-space-between flex-wrap ga-3">
              <div class="d-flex align-center ga-3">
                <div class="header-icon-wrap">
                  <v-icon icon="mdi-forum" size="28" color="white" />
                </div>
                <div>
                  <div class="header-title">{{ packDisplayName }}</div>
                  <div class="header-subtitle">
                    {{ selectedPack?.description || 'Facilitated multi-agent decision meeting' }}
                  </div>
                </div>
              </div>
              <v-chip
                :color="statusChipColor"
                variant="flat"
                size="small"
                class="text-uppercase font-weight-bold"
              >
                <v-icon start :icon="statusIcon" size="14" />
                {{ statusText }}
              </v-chip>
            </div>

            <div v-if="topic && status !== 'idle'" class="topic-display mt-4">
              <span class="topic-label">TOPIC</span>
              <span class="topic-text">{{ topic }}</span>
            </div>

            <div v-if="status === 'idle'" class="d-flex flex-column ga-3 mt-4">
              <v-select
                v-model="selectedPack"
                :items="availablePacks"
                item-title="name"
                item-value="path"
                label="Meeting Pack"
                :hint="selectedPack?.description || 'Select a meeting configuration pack'"
                persistent-hint
                density="compact"
                variant="outlined"
                prepend-inner-icon="mdi-package-variant"
                class="context-path-input"
                clearable
                return-object
                no-data-text="No meeting packs found"
              />
              <v-text-field
                v-model="topicInput"
                label="Meeting Topic"
                hint="The specific topic or question for this meeting"
                persistent-hint
                density="compact"
                variant="outlined"
                prepend-inner-icon="mdi-text-box"
                class="context-path-input"
                clearable
                @keydown.enter="handleStartMeeting"
              />
            </div>

            <div class="d-flex align-center ga-3 mt-4 flex-wrap">
              <v-btn
                prepend-icon="mdi-play-circle"
                color="amber-darken-2"
                variant="flat"
                :loading="status === 'active'"
                :disabled="status === 'active' || !canStart"
                @click="handleStartMeeting"
              >
                Start Meeting
              </v-btn>
              <v-btn
                prepend-icon="mdi-restore"
                variant="tonal"
                color="grey"
                :disabled="status === 'active'"
                @click="handleReset"
              >
                Reset
              </v-btn>
              <v-spacer />
              <div v-if="elapsedDisplay" class="elapsed-time">
                <v-icon icon="mdi-timer-outline" size="18" class="mr-1" />
                {{ elapsedDisplay }}
              </div>
            </div>
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Agent Personas + Transcript -->
    <v-row class="mt-3">
      <!-- Agent Panel -->
      <v-col cols="12" md="3">
        <v-card class="agents-card rounded-lg" variant="flat">
          <div class="agents-header pa-3">
            <v-icon icon="mdi-account-group" size="18" class="mr-2" />
            PARTICIPANTS
          </div>
          <div class="agents-list">
            <div
              v-for="agent in agentProfiles"
              :key="agent.id"
              class="agent-row pa-3"
              :class="{ 'agent-speaking': lastSpeaker === agent.id }"
            >
              <v-avatar :color="agent.color" size="32" class="mr-2">
                <v-icon :icon="agent.icon" size="18" color="white" />
              </v-avatar>
              <div class="agent-info">
                <div class="agent-name">{{ agent.shortName }}</div>
                <div class="agent-role">{{ agent.role }}</div>
              </div>
              <v-icon
                v-if="lastSpeaker === agent.id"
                icon="mdi-microphone"
                size="14"
                color="amber-darken-2"
                class="ml-auto pulse-icon"
              />
            </div>
          </div>
        </v-card>

        <v-card
          v-if="governanceDecision"
          class="architect-card rounded-lg mt-3"
          variant="flat"
        >
          <div class="architect-header pa-3">
            <v-icon icon="mdi-gavel" size="18" class="mr-2" />
            {{ governancePhaseLabel }}
          </div>
          <div class="pa-3">
            <v-chip
              :color="governanceDecisionColor"
              variant="flat"
              size="small"
              class="font-weight-bold"
            >
              {{ governanceDecision }}
            </v-chip>
          </div>
        </v-card>
      </v-col>

      <!-- Live Transcript -->
      <v-col cols="12" md="9">
        <v-card class="transcript-card rounded-lg" variant="flat">
          <div class="transcript-header pa-3 d-flex align-center">
            <v-icon icon="mdi-script-text" size="18" class="mr-2" />
            LIVE TRANSCRIPT
            <v-spacer />
            <v-chip size="x-small" variant="tonal" color="grey">
              {{ transcript.length }} messages
            </v-chip>
          </div>

          <div ref="transcriptContainer" class="transcript-body">
            <div v-if="transcript.length === 0" class="transcript-empty">
              <v-icon icon="mdi-message-text-clock" size="48" color="grey-darken-1" />
              <div class="mt-2 text-grey-darken-1">
                Waiting for meeting to begin...
              </div>
            </div>

            <TransitionGroup name="message-enter" tag="div">
              <div
                v-for="(entry, idx) in transcript"
                :key="entry.timestamp + '-' + idx"
                class="transcript-entry"
                :class="[
                  'msg-type-' + (entry.message_type || 'comment').toLowerCase(),
                  { 'msg-facilitator': isFacilitator(entry.from_agent) },
                ]"
              >
                <div class="entry-header">
                  <v-avatar
                    :color="getAgentColor(entry.from_agent)"
                    size="24"
                    class="mr-2"
                  >
                    <v-icon
                      :icon="getAgentIcon(entry.from_agent)"
                      size="14"
                      color="white"
                    />
                  </v-avatar>
                  <span class="entry-agent">{{ formatAgentName(entry.from_agent) }}</span>
                  <v-chip
                    size="x-small"
                    :color="getMessageTypeColor(entry.message_type)"
                    variant="tonal"
                    class="ml-2"
                  >
                    {{ entry.message_type }}
                  </v-chip>
                  <span class="entry-phase ml-2">P{{ entry.phase || '?' }}</span>
                </div>
                <div class="entry-body" v-html="renderContent(entry)" />
              </div>
            </TransitionGroup>
          </div>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import { sanitizeHtml } from './markdown'

// ── Types ────────────────────────────────────────────────────────────────

interface TranscriptEntry {
  from_agent: string
  message_type: string
  content: any
  phase?: number
  timestamp: string
}

interface MeetingPack {
  name: string
  path: string
  description: string
  template_name: string
  phases: { id: number; label: string }[]
  agents: AgentProfile[]
}

interface AgentProfile {
  id: string
  shortName: string
  role: string
  icon: string
  color: string
  soul?: string
}

// ── WebSocket ────────────────────────────────────────────────────────────

const wsMessage = ref<any>(null)
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

function connectWebSocket(): void {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${window.location.host}/ws`
  ws = new WebSocket(url)

  ws.onmessage = (event) => {
    try {
      wsMessage.value = JSON.parse(event.data)
    } catch { /* ignore non-JSON */ }
  }

  ws.onclose = () => {
    reconnectTimer = setTimeout(connectWebSocket, 3000)
  }

  ws.onerror = () => {
    ws?.close()
  }
}

onMounted(() => connectWebSocket())
onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws?.close()
})

// ── Reactive state ───────────────────────────────────────────────────────

const status = ref<'idle' | 'active' | 'finished'>('idle')
const topic = ref('')
const topicInput = ref('')
const availablePacks = ref<MeetingPack[]>([])
const selectedPack = ref<MeetingPack | null>(null)
const currentPhase = ref(0)
const transcript = ref<TranscriptEntry[]>([])
const governanceDecision = ref('')
const lastSpeaker = ref('')
const startTime = ref<number | null>(null)
const elapsedSeconds = ref(0)
const transcriptContainer = ref<HTMLElement | null>(null)
const dynamicAgents = ref<AgentProfile[]>([])

let timerInterval: ReturnType<typeof setInterval> | null = null

// ── Computed ─────────────────────────────────────────────────────────────

const packDisplayName = computed(() => {
  if (selectedPack.value) {
    return selectedPack.value.name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }
  return 'Meeting Arena'
})

const canStart = computed(() => !!selectedPack.value && !!topicInput.value.trim())

const DEFAULT_PHASES = [
  { id: 1, label: 'Proposal' },
  { id: 2, label: 'Discussion' },
  { id: 3, label: 'Synthesis' },
  { id: 4, label: 'Governance' },
]

const phases = computed(() =>
  selectedPack.value?.phases?.length ? selectedPack.value.phases : DEFAULT_PHASES
)

const agentProfiles = computed(() => {
  if (selectedPack.value?.agents?.length) return selectedPack.value.agents
  return dynamicAgents.value
})

const agentMap = computed(() =>
  Object.fromEntries(agentProfiles.value.map(a => [a.id, a]))
)

const statusChipColor = computed(() => {
  if (status.value === 'active') return 'amber-darken-2'
  if (status.value === 'finished') return 'green'
  return 'grey'
})

const statusIcon = computed(() => {
  if (status.value === 'active') return 'mdi-loading mdi-spin'
  if (status.value === 'finished') return 'mdi-check-circle'
  return 'mdi-circle-outline'
})

const statusText = computed(() => {
  if (status.value === 'active') return 'In Progress'
  if (status.value === 'finished') return 'Complete'
  return 'Idle'
})

const governanceDecisionColor = computed(() => {
  const d = governanceDecision.value.toUpperCase()
  if (['APPROVED', 'RELEASE'].includes(d)) return 'green'
  if (d === 'CONDITIONAL') return 'amber-darken-2'
  if (['REJECTED', 'HOLD'].includes(d)) return 'red'
  return 'grey'
})

const governancePhaseLabel = computed(() => {
  const last = phases.value[phases.value.length - 1]
  return last?.label?.toUpperCase() || 'GOVERNANCE'
})

const elapsedDisplay = computed(() => {
  if (!elapsedSeconds.value) return ''
  const m = Math.floor(elapsedSeconds.value / 60)
  const s = elapsedSeconds.value % 60
  return `${m}:${s.toString().padStart(2, '0')}`
})

// ── Agent helpers ────────────────────────────────────────────────────────

const FALLBACK_COLORS = ['#6D4C41', '#1565C0', '#6A1B9A', '#E65100', '#00838F', '#2E7D32', '#AD1457', '#4527A0']

const VIRTUAL_AGENTS: Record<string, AgentProfile> = {
  'final-reviewer': {
    id: 'final-reviewer', shortName: 'Final Reviewer',
    role: 'Independent Reviewer', icon: 'mdi-shield-star', color: '#7C4DFF',
  },
}

function buildAgentProfilesFromIds(ids: string[]): AgentProfile[] {
  const packMatch = availablePacks.value.find(p =>
    ids.length > 0 && ids.every(id => p.agents.some(a => a.id === id))
  )
  if (packMatch) {
    selectedPack.value = packMatch
    return []
  }
  return ids.map((id, i) => {
    const words = id.replace(/-/g, ' ').split(' ')
    const shortName = words.map(w => w.charAt(0).toUpperCase() + w.slice(1)).slice(-2).join(' ')
    return { id, shortName, role: '', icon: 'mdi-account', color: FALLBACK_COLORS[i % FALLBACK_COLORS.length] }
  })
}

function isFacilitator(agentId: string): boolean {
  return agentId?.includes('facilitator') ?? false
}

function getAgentColor(agentId: string): string {
  return agentMap.value[agentId]?.color || VIRTUAL_AGENTS[agentId]?.color || '#616161'
}

function getAgentIcon(agentId: string): string {
  return agentMap.value[agentId]?.icon || VIRTUAL_AGENTS[agentId]?.icon || 'mdi-account'
}

function formatAgentName(agentId: string): string {
  return agentMap.value[agentId]?.shortName || VIRTUAL_AGENTS[agentId]?.shortName || agentId
}

function getMessageTypeColor(msgType: string): string {
  const map: Record<string, string> = {
    PROPOSAL_SUBMISSION: 'blue', PROPOSAL_REVISION: 'indigo',
    COMMENT: 'grey', AGREE: 'green', DISAGREE: 'red',
    CHANGE_REQUEST: 'orange', ARCHITECT_APPROVAL: 'purple',
    LEADERSHIP_DECISION: 'purple', MEETING_NOTES: 'teal',
    FINAL_REVIEW: 'deep-purple', CLOSE_TOPIC: 'brown', REFRAME: 'cyan',
  }
  return map[msgType] || 'grey'
}

// ── Content rendering ────────────────────────────────────────────────────

function stripCodeFences(str: string): string {
  return str.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim()
}

function tryParseJson(str: string): any | null {
  const cleaned = stripCodeFences(str)
  try { return JSON.parse(cleaned) } catch {
    const match = cleaned.match(/\{[\s\S]*\}/)
    if (match) { try { return JSON.parse(match[0]) } catch { /* noop */ } }
    return null
  }
}

function unwrapNestedContent(obj: any): any {
  if (!obj || typeof obj !== 'object') return obj
  if (obj.content && typeof obj.content === 'object' && obj.message_type) {
    return { ...obj.content, message_type: obj.message_type }
  }
  if (typeof obj.content === 'string' && obj.message_type && !obj.points?.length) {
    return { ...obj, points: [obj.content], content: undefined }
  }
  return obj
}

function resolveContent(raw: any): any {
  if (!raw || typeof raw !== 'object') return raw
  let c = unwrapNestedContent(raw)
  if (c.points && Array.isArray(c.points)) {
    for (const p of c.points) {
      if (typeof p === 'string' && p.includes('"message_type"')) {
        const parsed = tryParseJson(stripCodeFences(p))
        if (parsed && parsed.message_type) return unwrapNestedContent(parsed)
      }
    }
  }
  return c
}

function safeStr(v: any): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (Array.isArray(v)) return v.map(safeStr).join(', ')
  if (typeof v === 'object') {
    const vals = Object.values(v).filter(Boolean)
    return vals.length ? vals.map(safeStr).join(' — ') : JSON.stringify(v)
  }
  return String(v)
}

function formatObjectValue(v: any): string {
  if (typeof v === 'string') return v
  if (Array.isArray(v)) return v.map((item: any) =>
    typeof item === 'object' ? `  - ${Object.values(item).map(safeStr).join(' — ')}` : `  - ${item}`
  ).join('\n')
  if (typeof v === 'object') return Object.entries(v).map(([k2, v2]) =>
    `  **${k2.replace(/_/g, ' ')}:** ${safeStr(v2)}`
  ).join('\n')
  return String(v)
}

function renderStructuredObject(obj: any, depth = 0): string {
  const indent = '  '.repeat(depth)
  return Object.entries(obj).map(([k, v]) => {
    const label = k.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
    if (typeof v === 'string') return `${indent}- **${label}:** ${v}`
    if (Array.isArray(v)) return `${indent}- **${label}:**\n${v.map((item: any) => `${indent}  - ${safeStr(item)}`).join('\n')}`
    if (typeof v === 'object' && v !== null) return `${indent}- **${label}:**\n${renderStructuredObject(v, depth + 1)}`
    return `${indent}- **${label}:** ${v}`
  }).join('\n')
}

const METADATA_KEYS = new Set([
  'message_type', 'from_agent', 'id', 'timestamp', 'meeting_id',
  '_original_expected_type', 'phase',
])

function renderContentFields(obj: any): string {
  if (!obj || typeof obj !== 'object') return safeStr(obj)
  const payload = Object.fromEntries(Object.entries(obj).filter(([k]) => !METADATA_KEYS.has(k)))
  return Object.keys(payload).length ? renderStructuredObject(payload) : ''
}

function renderChangeRequest(cr: any): string {
  const parts: string[] = []
  if (cr.requirement) parts.push(`**Change:** ${typeof cr.requirement === 'object' ? renderStructuredObject(cr.requirement) : cr.requirement}`)
  if (cr.justification) parts.push(`**Why:** ${typeof cr.justification === 'object' ? renderStructuredObject(cr.justification) : cr.justification}`)
  if (cr.severity) parts.push(`*Severity: ${cr.severity}*`)
  if (cr.impact) parts.push(`**Impact:** ${typeof cr.impact === 'object' ? formatObjectValue(cr.impact) : cr.impact}`)
  if (!parts.length) parts.push(renderContentFields(cr))
  return parts.join('\n\n')
}

function renderDisagree(d: any): string {
  const parts: string[] = []
  if (d.severity) parts.push(`**Severity:** ${d.severity}`)
  if (d.blocker_description) parts.push(`**Blocker:** ${d.blocker_description}`)
  if (d.required_changes && Array.isArray(d.required_changes)) {
    parts.push(`**Required Changes:**\n${d.required_changes.map((rc: any) => typeof rc === 'string' ? `- ${rc}` : `- ${safeStr(rc)}`).join('\n')}`)
  }
  if (!parts.length) parts.push(renderContentFields(d))
  return parts.join('\n\n')
}

function extractReadableFromBrokenJson(raw: string): string {
  const cleaned = stripCodeFences(raw)
  const parts: string[] = []
  const fieldPatterns: [string, string][] = [
    ['title', 'Title'], ['problem_statement', 'Problem'],
    ['proposed_solution', 'Solution'], ['core_change', 'Core Change'],
    ['requirement', 'Change'], ['change', 'Change'],
    ['justification', 'Why'], ['blocker_description', 'Blocker'],
    ['severity', 'Severity'], ['risk_scenario', 'Risk'],
    ['regulatory_impact', 'Regulatory'], ['rationale', 'Rationale'],
    ['executive_summary', 'Summary'], ['decision', 'Decision'],
    ['priority', 'Priority'], ['impact', 'Impact'],
  ]
  for (const [field, label] of fieldPatterns) {
    const re = new RegExp(`"${field}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`, 'g')
    let match
    while ((match = re.exec(cleaned)) !== null) {
      const val = match[1].replace(/\\n/g, ' ').replace(/\\"/g, '"').trim()
      if (val) parts.push(`**${label}:** ${val}`)
    }
  }
  return parts.length > 0 ? parts.join('\n\n') : `- ${cleaned.slice(0, 400)}...`
}

function renderContent(entry: TranscriptEntry): string {
  const rawContent = entry.content
  if (!rawContent) return ''
  if (typeof rawContent === 'string') return sanitizeHtml(marked.parse(rawContent) as string)

  const content = resolveContent(rawContent)
  const msgType = content.message_type || entry.message_type
  const parts: string[] = []

  if (msgType === 'PROPOSAL_SUBMISSION' || msgType === 'PROPOSAL_REVISION') {
    const docKeys = ['updated_spike_document', 'spike_document', 'updated_release_plan', 'release_plan', 'updated_proposal', 'proposal']
    let doc: any = null
    for (const k of docKeys) {
      if (content[k] && typeof content[k] === 'object') { doc = content[k]; break }
    }
    if (!doc) {
      const candidateKey = Object.keys(content).find(k =>
        !METADATA_KEYS.has(k) && typeof content[k] === 'object' && content[k] !== null &&
        !Array.isArray(content[k]) && (content[k].title || content[k].problem_statement || content[k].proposed_solution)
      )
      if (candidateKey) doc = content[candidateKey]
    }
    if (doc) {
      if (doc.title) parts.push(`**${doc.title}**`)
      if (doc.problem_statement) parts.push(doc.problem_statement)
      if (doc.proposed_solution) {
        if (typeof doc.proposed_solution === 'object' && !Array.isArray(doc.proposed_solution)) {
          const solParts = Object.entries(doc.proposed_solution).map(([k, v]) => {
            const label = k.replace(/_/g, ' ').replace(/\b\w/g, (ch: string) => ch.toUpperCase())
            if (typeof v === 'object') {
              const sub = Object.entries(v as Record<string, any>).map(([sk, sv]) => {
                const slabel = sk.replace(/_/g, ' ').replace(/\b\w/g, (ch: string) => ch.toUpperCase())
                return typeof sv === 'object' ? `- **${slabel}:** ${Object.values(sv as Record<string, any>).join('; ')}` : `- **${slabel}:** ${sv}`
              }).join('\n')
              return `**${label}:**\n${sub}`
            }
            return `**${label}:** ${v}`
          })
          parts.push(`**Solution:**\n${solParts.join('\n\n')}`)
        } else {
          const sol = Array.isArray(doc.proposed_solution)
            ? doc.proposed_solution.map((s: any) => `- ${safeStr(s)}`).join('\n')
            : safeStr(doc.proposed_solution)
          parts.push(`**Solution:**\n${sol}`)
        }
      }
      for (const section of ['impact_areas', 'rollback_strategy', 'timeline', 'assumptions', 'enhancements']) {
        const val = doc[section]
        if (!val) continue
        const label = section.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
        if (Array.isArray(val)) {
          parts.push(`**${label}:**\n${val.map((item: any) => typeof item === 'object'
            ? `- **${item.area || item.name || Object.keys(item)[0]}:** ${item.details || item.description || item.duration || Object.values(item).slice(1).join(' — ')}`
            : `- ${item}`
          ).join('\n')}`)
        } else if (typeof val === 'object') {
          parts.push(`**${label}:**\n${Object.entries(val).map(([k, v]) => `- **${k.replace(/_/g, ' ')}:** ${safeStr(v)}`).join('\n')}`)
        } else {
          parts.push(`**${label}:**\n${val}`)
        }
      }
    }
    if (content.feedback_addressed) {
      if (typeof content.feedback_addressed === 'object' && !Array.isArray(content.feedback_addressed)) {
        for (const [key, val] of Object.entries(content.feedback_addressed)) {
          const label = key.replace(/_/g, ' ').replace(/\b\w/g, (ch: string) => ch.toUpperCase())
          if (Array.isArray(val)) parts.push(`**${label}:**\n${(val as any[]).map((f: any) => `- ${safeStr(f)}`).join('\n')}`)
          else parts.push(`**${label}:** ${safeStr(val)}`)
        }
      } else if (Array.isArray(content.feedback_addressed)) {
        parts.push(`**Feedback Addressed:**\n${content.feedback_addressed.map((f: any) => `- ${safeStr(f)}`).join('\n')}`)
      }
    }

  } else if (msgType === 'COMMENT') {
    const originalType = content._original_expected_type
    if (originalType && (content.requirement || content.justification || content.blocker_description)) {
      if (originalType === 'CHANGE_REQUEST' || content.requirement) parts.push(renderChangeRequest(content))
      else if (originalType === 'DISAGREE' || content.blocker_description) parts.push(renderDisagree(content))
    }
    if (!parts.length && content.points && Array.isArray(content.points)) {
      for (const p of content.points) {
        if (typeof p === 'object' && p !== null) {
          const pType = p.message_type || originalType
          if (pType === 'CHANGE_REQUEST' || p.requirement) parts.push(renderChangeRequest(p))
          else if (pType === 'DISAGREE' || p.blocker_description) parts.push(renderDisagree(p))
          else parts.push(renderStructuredObject(p))
        } else if (typeof p === 'string') {
          const nested = tryParseJson(p)
          if (nested && typeof nested === 'object') {
            const nType = nested.message_type || originalType
            if (nType === 'CHANGE_REQUEST' || nested.requirement) parts.push(renderChangeRequest(nested))
            else if (nType === 'DISAGREE' || nested.blocker_description) parts.push(renderDisagree(nested))
            else if (nested.message_type) parts.push(renderContent({ ...entry, content: nested, message_type: nested.message_type }))
            else parts.push(`- ${p}`)
          } else parts.push(`- ${p}`)
        }
      }
    }
    if (!parts.length && content.points && Array.isArray(content.points)) {
      parts.push(...content.points.filter((p: any) => typeof p === 'string').map((p: string) => `- ${p}`))
    }
    if (!parts.length && typeof content.content === 'string' && content.content) {
      parts.push(content.content)
    }

  } else if (msgType === 'CHANGE_REQUEST') {
    if (content.changes && Array.isArray(content.changes)) content.changes.forEach((cr: any) => parts.push(renderChangeRequest(cr)))
    else parts.push(renderChangeRequest(content))

  } else if (msgType === 'DISAGREE') {
    parts.push(renderDisagree(content))

  } else if (msgType === 'ARCHITECT_APPROVAL' || msgType === 'LEADERSHIP_DECISION') {
    if (content.decision) parts.push(`**Decision: ${content.decision}**`)
    if (content.rationale) {
      if (typeof content.rationale === 'object' && !Array.isArray(content.rationale)) {
        const rationaleLines = Object.entries(content.rationale).map(([k, v]) => {
          const label = k.replace(/_/g, ' ').replace(/\b\w/g, (ch: string) => ch.toUpperCase())
          if (Array.isArray(v)) return `**${label}:**\n${v.map((item: any) => typeof item === 'object' ? `- ${Object.values(item).map(safeStr).join(' — ')}` : `- ${item}`).join('\n')}`
          if (typeof v === 'object' && v !== null) return `**${label}:**\n${renderStructuredObject(v, 1)}`
          return `**${label}:** ${v}`
        })
        parts.push(rationaleLines.join('\n\n'))
      } else if (Array.isArray(content.rationale)) {
        parts.push(content.rationale.map((i: any) => `- ${safeStr(i)}`).join('\n'))
      } else parts.push(safeStr(content.rationale))
    }
    const conditionsRaw = content.conditions || content.requirements
    if (conditionsRaw && Array.isArray(conditionsRaw)) {
      const conds = conditionsRaw.map((c: any) => {
        if (typeof c !== 'object') return `- ${c}`
        const label = c.requirement || c.id || c.description || 'Condition'
        const owner = c.owner ? ` *(${c.owner})*` : ''
        const details = c.details ? `\n  ${safeStr(c.details)}` : ''
        const criteria = c.acceptance_criteria ? `\n  *Acceptance:* ${safeStr(c.acceptance_criteria)}` : ''
        return `- **${label}**${owner}${details}${criteria}`
      }).join('\n')
      parts.push(`**Conditions:**\n${conds}`)
    } else if (conditionsRaw && typeof conditionsRaw === 'object') {
      parts.push(`**Conditions:**\n${renderStructuredObject(conditionsRaw, 0)}`)
    }
    if (content.recommended_messaging && typeof content.recommended_messaging === 'object' && !Array.isArray(content.recommended_messaging)) {
      parts.push(`**Recommended Messaging:**\n${renderStructuredObject(content.recommended_messaging, 0)}`)
    }

  } else if (msgType === 'MEETING_NOTES') {
    if (content.executive_summary) parts.push(content.executive_summary)
    const listFields: Record<string, string> = {
      key_objections: 'Key Objections', key_concerns: 'Key Concerns',
      accepted_compromises: 'Compromises', recommended_messaging: 'Recommended Messaging',
      action_items: 'Action Items', risk_register: 'Risk Register', decisions: 'Decisions',
    }
    for (const [field, label] of Object.entries(listFields)) {
      const val = content[field]
      if (val && Array.isArray(val) && val.length > 0) {
        const items = val.map((item: any) => {
          if (typeof item === 'object' && item !== null) {
            const pairs = Object.entries(item).filter(([, v]) => v != null && v !== '')
              .map(([k, v]) => `**${k.replace(/_/g, ' ').replace(/\b\w/g, (ch: string) => ch.toUpperCase())}:** ${v}`)
            return `- ${pairs.join(' | ')}`
          }
          return `- ${safeStr(item)}`
        }).join('\n')
        parts.push(`**${label}:**\n${items}`)
      }
    }
    const rulingField = content.architect_final_ruling || content.leadership_decision
    if (rulingField) {
      if (typeof rulingField === 'object') {
        const rp = []
        if (rulingField.decision) rp.push(`**Final Decision: ${rulingField.decision}**`)
        if (rulingField.rationale) rp.push(rulingField.rationale)
        if (rulingField.compliance_alignment) rp.push(`*${rulingField.compliance_alignment}*`)
        parts.push(rp.join('\n'))
      } else parts.push(`**Final Decision:** ${rulingField}`)
    }
    if (content.audit_trail && Array.isArray(content.audit_trail) && content.audit_trail.length > 0) {
      parts.push(`**Audit Trail:**\n${content.audit_trail.map((a: any) =>
        typeof a === 'object' ? `- **${a.agent || '?'}** — ${a.action || ''}: ${a.outcome || ''}` : `- ${a}`
      ).join('\n')}`)
    }

  } else if (msgType === 'FINAL_REVIEW') {
    if (content.overall_assessment) parts.push(`**Overall Assessment:** ${safeStr(content.overall_assessment)}`)
    if (content.decision_quality) parts.push(`**Decision Quality:** ${safeStr(content.decision_quality)}`)

    if (content.process_quality && typeof content.process_quality === 'object') {
      const pq = content.process_quality
      const pqParts: string[] = []
      if (pq.facilitator_effectiveness) pqParts.push(`- **Facilitator:** ${safeStr(pq.facilitator_effectiveness)}`)
      if (pq.agent_utilization) {
        const au = pq.agent_utilization
        if (typeof au === 'object' && au !== null && !Array.isArray(au)) {
          const lines: string[] = ['- **Agent Utilization:**']
          const ratios = au.ratios || au.turns_per_agent || au
          for (const [agent, val] of Object.entries(ratios)) lines.push(`  - ${agent}: ${val}`)
          if (au.dominant_agents?.length) lines.push(`  - *Dominant:* ${au.dominant_agents.join(', ')}`)
          if (au.underutilized_agents?.length) lines.push(`  - *Underutilized:* ${au.underutilized_agents.join(', ')}`)
          pqParts.push(lines.join('\n'))
        } else pqParts.push(`- **Agent Utilization:** ${safeStr(au)}`)
      }
      if (pq.discussion_balance) pqParts.push(`- **Discussion Balance:** ${safeStr(pq.discussion_balance)}`)
      if (pqParts.length) parts.push(`**Process Quality:**\n${pqParts.join('\n')}`)
    }

    if (content.strengths?.length) {
      parts.push(`**Strengths:**\n${content.strengths.map((i: any) => {
        if (typeof i === 'object' && i !== null) {
          const desc = i.description || i.text || safeStr(i)
          const agents = i.agents?.length ? ` *(${i.agents.join(', ')})*` : ''
          return `- ${desc}${agents}`
        }
        return `- ${i}`
      }).join('\n')}`)
    }

    if (content.meta_observations) parts.push(`**Meta-Observations:** ${safeStr(content.meta_observations)}`)

    if (content.blind_spots?.length) {
      parts.push(`**Blind Spots:**\n${content.blind_spots.map((i: any) => {
        if (typeof i === 'object' && i !== null) {
          const desc = i.description || i.text || safeStr(i)
          const questions = i.missed_questions?.length ? '\n' + i.missed_questions.map((q: string) => `  - *${q}*`).join('\n') : ''
          return `- ${desc}${questions}`
        }
        return `- ${i}`
      }).join('\n')}`)
    }

    if (content.recommendations?.length) {
      parts.push(`**Recommendations:**\n${content.recommendations.map((i: any) => {
        if (typeof i === 'object' && i !== null) {
          const action = i.action || i.description || safeStr(i)
          const meta: string[] = []
          if (i.timing) meta.push(`${i.timing}`)
          if (i.owner) meta.push(`Owner: ${i.owner}`)
          if (i.priority) meta.push(`${i.priority}`)
          const suffix = meta.length ? ` *(${meta.join(' | ')})*` : ''
          const rationale = i.rationale ? `\n  ${i.rationale}` : ''
          return `- ${action}${suffix}${rationale}`
        }
        return `- ${i}`
      }).join('\n')}`)
    }

    if (content.evidence_quality) {
      const eq = content.evidence_quality
      if (typeof eq === 'object' && !Array.isArray(eq)) {
        const eqParts: string[] = []
        const renderEvidenceList = (items: any[], label: string) => {
          if (!items?.length) return
          eqParts.push(`**${label}:**`)
          for (const e of items) {
            if (typeof e === 'object' && e !== null) {
              const claim = e.claim || e.evidence || e.text || safeStr(e)
              const agent = e.agent || ''
              const turn = e.turn
              const citation = agent && turn ? ` *(${agent}, turn ${turn})*` : (agent ? ` *(${agent})*` : '')
              const detail = e.concern || e.usage || e.verdict || ''
              eqParts.push(`- ${claim}${citation}${detail ? `\n  *${detail}*` : ''}`)
            } else eqParts.push(`- ${e}`)
          }
        }
        for (const [key, label] of [
          ['fabricated_or_suspicious', 'Fabricated or Suspicious'],
          ['suspicious_or_misused', 'Flagged Evidence'],
          ['fabricated_claims', 'Fabricated Claims'],
          ['unverified_statistics', 'Unverified Statistics'],
        ] as const) renderEvidenceList(eq[key], label)
        for (const [key, label] of [
          ['well_used', 'Well-Used Evidence'],
          ['plausible_and_well_used', 'Well-Used Evidence'],
          ['plausible_evidence', 'Plausible Evidence'],
        ] as const) renderEvidenceList(eq[key], label)
        if (eqParts.length) parts.push(`**Evidence Quality:**\n${eqParts.join('\n')}`)
        else parts.push(`**Evidence Quality:** ${safeStr(eq)}`)
      } else parts.push(`**Evidence Quality:** ${safeStr(eq)}`)
    }

    if (content.confidence_score != null) parts.push(`**Confidence Score:** ${content.confidence_score}/10`)
    if (content.confidence_gap) parts.push(`**What Would Raise It:** ${safeStr(content.confidence_gap)}`)
  }

  // Fallbacks
  if (!parts.length && content.points && Array.isArray(content.points)) {
    for (const p of content.points) {
      if (typeof p === 'object' && p !== null) {
        if (p.message_type === 'CHANGE_REQUEST' || p.requirement) parts.push(renderChangeRequest(p))
        else if (p.message_type === 'DISAGREE' || p.blocker_description) parts.push(renderDisagree(p))
        else if (p.message_type) parts.push(renderContent({ ...entry, content: p, message_type: p.message_type }))
        else parts.push(`- ${safeStr(p)}`)
      } else if (typeof p === 'string') {
        const nested = tryParseJson(p)
        if (nested && typeof nested === 'object' && nested.message_type) {
          const unwrapped = unwrapNestedContent(nested)
          if (unwrapped.requirement || unwrapped.message_type === 'CHANGE_REQUEST') parts.push(renderChangeRequest(unwrapped))
          else parts.push(renderContent({ ...entry, content: unwrapped, message_type: unwrapped.message_type || nested.message_type }))
        } else if (p.includes('"message_type"')) parts.push(extractReadableFromBrokenJson(p))
        else parts.push(`- ${p}`)
      }
    }
  }

  if (!parts.length && content.blocker_description) parts.push(renderDisagree(content))
  if (!parts.length && content.requirement) parts.push(renderChangeRequest(content))
  if (!parts.length && content.changes && Array.isArray(content.changes)) content.changes.forEach((cr: any) => parts.push(renderChangeRequest(cr)))

  if (!parts.length) {
    const generic = renderContentFields(content)
    if (generic) parts.push(generic)
    else {
      const display = JSON.stringify(content, null, 2)
      return `<pre class="entry-json">${display.slice(0, 600)}</pre>`
    }
  }

  return sanitizeHtml(marked.parse(parts.join('\n\n')) as string)
}

// ── Timer ────────────────────────────────────────────────────────────────

function startTimer(): void {
  startTime.value = Date.now()
  elapsedSeconds.value = 0
  timerInterval = setInterval(() => {
    if (startTime.value) elapsedSeconds.value = Math.floor((Date.now() - startTime.value) / 1000)
  }, 1000)
}

function stopTimer(): void {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
}

function scrollToBottom(): void {
  nextTick(() => {
    const el = transcriptContainer.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// ── Watch WebSocket messages ─────────────────────────────────────────────

watch(wsMessage, (msg: any) => {
  if (!msg || msg.type !== 'meeting_update') return
  const meetingType = msg.meeting_type
  const decision = msg.architect_decision || msg.governance_decision || ''

  if (meetingType === 'meeting_start') {
    status.value = 'active'
    topic.value = msg.topic || ''
    currentPhase.value = 1
    transcript.value = []
    governanceDecision.value = ''
    if (msg.agents?.length && !agentProfiles.value.length) {
      dynamicAgents.value = buildAgentProfilesFromIds(msg.agents)
    }
    startTimer()
  } else if (meetingType === 'phase_complete') {
    currentPhase.value = (msg.phase || 0) + 1
    if (decision) governanceDecision.value = decision
  } else if (meetingType === 'meeting_turn') {
    transcript.value.push({
      from_agent: msg.from_agent || '',
      message_type: msg.message_type || 'COMMENT',
      content: msg.content || '',
      phase: msg.phase,
      timestamp: msg.timestamp || '',
    })
    lastSpeaker.value = msg.from_agent || ''
    scrollToBottom()
  } else if (meetingType === 'meeting_finish') {
    status.value = 'finished'
    if (decision) governanceDecision.value = decision
    if (msg.elapsed_seconds) elapsedSeconds.value = Math.round(msg.elapsed_seconds)
    stopTimer()
  }
})

// ── Actions ──────────────────────────────────────────────────────────────

async function handleStartMeeting(): Promise<void> {
  if (!canStart.value) return
  try {
    status.value = 'active'
    transcript.value = []
    currentPhase.value = 1
    governanceDecision.value = ''
    topic.value = topicInput.value
    startTimer()
    await fetch('/api/meeting/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic: topicInput.value,
        meeting_pack: selectedPack.value?.path || '',
      }),
    })
  } catch (err) {
    console.error('Failed to start meeting:', err)
    status.value = 'idle'
    stopTimer()
  }
}

async function handleReset(): Promise<void> {
  try {
    await fetch('/api/meeting/reset', { method: 'POST' })
    status.value = 'idle'
    topic.value = ''
    currentPhase.value = 0
    transcript.value = []
    governanceDecision.value = ''
    lastSpeaker.value = ''
    elapsedSeconds.value = 0
    stopTimer()
  } catch (err) {
    console.error('Failed to reset:', err)
  }
}

async function fetchCurrentState(): Promise<void> {
  try {
    const res = await fetch('/api/meeting/current')
    const data = await res.json()
    if (data.status === 'active') {
      status.value = 'active'
      topic.value = data.topic || ''
      currentPhase.value = data.phase || 1
      transcript.value = data.transcript || []
      const dec = data.architect_decision || data.governance_decision || ''
      if (dec) governanceDecision.value = dec
      if (data.agents?.length && !agentProfiles.value.length) {
        dynamicAgents.value = buildAgentProfilesFromIds(data.agents)
      }
      if (data.start_time) {
        startTime.value = new Date(data.start_time).getTime()
        elapsedSeconds.value = Math.floor((Date.now() - startTime.value) / 1000)
        startTimer()
      }
      scrollToBottom()
    } else if (data.status === 'finished') {
      status.value = 'finished'
      topic.value = data.topic || ''
      currentPhase.value = (phases.value.length || 4) + 1
      transcript.value = data.transcript || []
      governanceDecision.value = data.architect_decision || data.governance_decision || ''
      if (data.elapsed_seconds) elapsedSeconds.value = Math.round(data.elapsed_seconds)
      if (data.agents?.length && !agentProfiles.value.length) {
        dynamicAgents.value = buildAgentProfilesFromIds(data.agents)
      }
    }
  } catch { /* server not running */ }
}

async function fetchMeetingPacks(): Promise<void> {
  try {
    const res = await fetch('/api/meeting/packs')
    const data = await res.json()
    availablePacks.value = data
    if (data.length === 1) selectedPack.value = data[0]
  } catch { /* noop */ }
}

onMounted(() => {
  fetchCurrentState()
  fetchMeetingPacks()
})
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=DM+Sans:wght@400;500;600;700&display=swap');

.meeting-arena {
  font-family: 'DM Sans', sans-serif;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  min-height: 100vh;
}

/* Phase Tracker */
.phase-tracker {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  position: relative;
  padding: 8px 0;
}
.phase-step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  z-index: 1;
}
.phase-number {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}
.phase-pending {
  color: rgba(255, 255, 255, 0.3);
  background: rgba(255, 255, 255, 0.04);
}
.phase-pending .phase-number {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.3);
}
.phase-active {
  color: #FFB300;
  background: rgba(255, 179, 0, 0.12);
  box-shadow: 0 0 20px rgba(255, 179, 0, 0.15);
}
.phase-active .phase-number {
  background: #FFB300;
  color: #1a1a2e;
}
.phase-done {
  color: #66BB6A;
  background: rgba(102, 187, 106, 0.08);
}
.phase-done .phase-number {
  background: #66BB6A;
  color: #1a1a2e;
}
.phase-check {
  color: #66BB6A;
}

/* Header Card */
.header-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(12px);
}
.header-inner {
  color: white;
}
.header-icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, #FFB300, #FF8F00);
  display: flex;
  align-items: center;
  justify-content: center;
}
.header-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.3px;
}
.header-subtitle {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}
.topic-display {
  background: rgba(255, 179, 0, 0.06);
  border-left: 3px solid #FFB300;
  padding: 12px 16px;
  border-radius: 0 8px 8px 0;
}
.topic-label {
  display: block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #FFB300;
  margin-bottom: 4px;
}
.topic-text {
  font-size: 18px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
}
.elapsed-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  color: rgba(255, 255, 255, 0.6);
  display: flex;
  align-items: center;
}
.context-path-input {
  max-width: 700px;
}
.context-path-input :deep(.v-field) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

/* Agents Card */
.agents-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.agents-header,
.architect-header,
.transcript-header {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: rgba(255, 255, 255, 0.4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
}
.agents-list {
  max-height: 420px;
  overflow-y: auto;
}
.agent-row {
  display: flex;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  transition: background 0.3s;
}
.agent-row:last-child {
  border-bottom: none;
}
.agent-speaking {
  background: rgba(255, 179, 0, 0.08);
}
.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.agent-role {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.35);
  letter-spacing: 0.3px;
}
.pulse-icon {
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

/* Architect Decision */
.architect-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

/* Transcript Card */
.transcript-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.transcript-body {
  max-height: 560px;
  overflow-y: auto;
  padding: 8px;
  scroll-behavior: smooth;
}
.transcript-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  opacity: 0.5;
}

/* Transcript Entries */
.transcript-entry {
  padding: 10px 14px;
  margin-bottom: 6px;
  border-radius: 8px;
  border-left: 3px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.02);
  transition: all 0.3s;
}
.transcript-entry:hover {
  background: rgba(255, 255, 255, 0.04);
}
.msg-type-proposal_submission {
  border-left-color: #42A5F5;
  background: rgba(66, 165, 245, 0.04);
}
.msg-type-proposal_revision {
  border-left-color: #7E57C2;
  background: rgba(126, 87, 194, 0.04);
}
.msg-type-change_request {
  border-left-color: #FFA726;
  background: rgba(255, 167, 38, 0.04);
}
.msg-type-disagree {
  border-left-color: #EF5350;
  background: rgba(239, 83, 80, 0.04);
}
.msg-type-agree {
  border-left-color: #66BB6A;
  background: rgba(102, 187, 106, 0.04);
}
.msg-type-architect_approval {
  border-left-color: #AB47BC;
  background: rgba(171, 71, 188, 0.06);
}
.msg-type-meeting_notes {
  border-left-color: #26A69A;
  background: rgba(38, 166, 154, 0.04);
}
.msg-type-final_review {
  border-left-color: #7C4DFF;
  background: rgba(124, 77, 255, 0.06);
  border-left-width: 4px;
}
.msg-facilitator {
  border-left-color: #8D6E63 !important;
  background: rgba(141, 110, 99, 0.06) !important;
}
.msg-type-close_topic,
.msg-type-reframe {
  border-left-color: #8D6E63;
  font-style: italic;
}

.entry-header {
  display: flex;
  align-items: center;
  margin-bottom: 6px;
}
.entry-agent {
  font-size: 12px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.75);
  letter-spacing: 0.3px;
}
.entry-phase {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.25);
}
.entry-body {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.65);
  word-break: break-word;
}
.entry-body :deep(strong) {
  color: rgba(255, 255, 255, 0.85);
  font-weight: 600;
}
.entry-body :deep(ul) {
  padding-left: 16px;
  margin: 4px 0;
}
.entry-body :deep(li) {
  margin-bottom: 2px;
}
.entry-body :deep(pre) {
  background: rgba(0, 0, 0, 0.3);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 11px;
  overflow-x: auto;
  font-family: 'JetBrains Mono', monospace;
  color: rgba(255, 255, 255, 0.6);
}
.entry-body :deep(p) {
  margin-bottom: 4px;
}
.entry-json {
  max-height: 200px;
  overflow-y: auto;
}

/* Transition */
.message-enter-enter-active {
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.message-enter-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

/* Scrollbar */
.transcript-body::-webkit-scrollbar,
.agents-list::-webkit-scrollbar {
  width: 5px;
}
.transcript-body::-webkit-scrollbar-track,
.agents-list::-webkit-scrollbar-track {
  background: transparent;
}
.transcript-body::-webkit-scrollbar-thumb,
.agents-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}
</style>
