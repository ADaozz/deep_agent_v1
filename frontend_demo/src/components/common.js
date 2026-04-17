import { THEMES } from "../constants.js";
import {
  formatFileSize,
  formatUtc8Timestamp,
  iconNameForArtifact,
  pendingUploadTone,
  statusClass,
  stepLabel,
  stepState,
} from "../utils.js";
import { icons } from "../icons.js";

export const Modal = {
  props: {
    open: Boolean,
    title: String,
    eyebrow: { type: String, default: "Agent Panel" },
    variant: { type: String, default: "" },
  },
  emits: ["close"],
  template: `
    <teleport to="body">
      <div v-if="open" :class="['modal-root', variant ? 'is-' + variant : '']">
        <button type="button" class="modal-backdrop" aria-label="关闭" @click="$emit('close')"></button>
        <div :class="['modal-card', variant ? 'is-' + variant : '']">
          <div class="modal-head">
            <div>
              <div class="modal-eyebrow">{{ eyebrow }}</div>
              <h3 class="modal-title">{{ title }}</h3>
            </div>
            <button type="button" class="icon-button" @click="$emit('close')">
              <component :is="icons.X" class="h-4 w-4" />
            </button>
          </div>
          <slot />
        </div>
      </div>
    </teleport>
  `,
  setup() {
    return { icons };
  },
};

export const IconForStep = {
  props: {
    status: String,
    compact: { type: Boolean, default: false },
  },
  computed: {
    state() {
      return stepState(this.status);
    },
    sizeClass() {
      return this.compact ? "h-3.5 w-3.5" : "h-4 w-4";
    },
    iconComponent() {
      if (this.state === "blocked") return icons.ShieldAlert;
      if (this.state === "running") return icons.LoaderCircle;
      if (this.state === "success") return icons.CheckCircle2;
      if (this.state === "error") return icons.XCircle;
      return icons.Circle;
    },
  },
  methods: { stepState },
  template: `
    <span :class="['status-icon', 'is-' + state, state === 'success' ? 'step-pop' : '']">
      <component :is="iconComponent" :class="[sizeClass, state === 'running' ? 'animate-spin' : '']" />
    </span>
  `,
};

export const SectionTitle = {
  props: {
    icon: [Object, Function],
    title: String,
    meta: String,
  },
  template: `
    <div class="message-section-title">
      <div class="message-section-heading">
        <component :is="icon" class="h-4 w-4" />
        <span>{{ title }}</span>
      </div>
      <span v-if="meta" class="message-section-meta">{{ meta }}</span>
    </div>
  `,
};

export const EmptyHint = {
  props: { text: String },
  template: `<div class="compact-hint">{{ text }}</div>`,
};

export const ChatBubble = {
  props: {
    kind: { type: String, default: "assistant" },
    title: String,
    eyebrow: String,
    icon: [Object, Function],
    accent: { type: String, default: "" },
    hideHeader: { type: Boolean, default: false },
  },
  template: `
    <article :class="['chat-row', kind === 'user' ? 'is-user' : '']">
      <div :class="['chat-bubble', kind === 'user' ? 'is-user' : '', accent]">
        <div v-if="!hideHeader" class="chat-bubble-head">
          <div class="chat-bubble-title">
            <component v-if="icon" :is="icon" class="h-4 w-4" />
            <span>{{ title }}</span>
          </div>
          <span v-if="eyebrow" class="chat-bubble-eyebrow">{{ eyebrow }}</span>
        </div>
        <div class="chat-bubble-body"><slot /></div>
      </div>
    </article>
  `,
};

export const StatCard = {
  props: {
    icon: [Object, Function],
    label: String,
    value: [String, Number],
  },
  template: `
    <div class="stat-card">
      <div class="stat-label">
        <component :is="icon" class="h-4 w-4" />
        <span>{{ label }}</span>
      </div>
      <div class="stat-value">{{ value }}</div>
    </div>
  `,
};

export const StatusCard = {
  props: {
    icon: [Object, Function],
    label: String,
    value: [String, Number],
    tone: String,
  },
  template: `
    <div :class="['stat-card', 'status-card', tone ? 'is-' + tone : '']">
      <div class="stat-label">
        <component :is="icon" :class="['h-4 w-4', tone === 'running' ? 'animate-spin' : '']" />
        <span>{{ label }}</span>
      </div>
      <div class="stat-value">{{ value }}</div>
    </div>
  `,
};

export const InfoCard = {
  props: {
    label: String,
    value: [String, Number],
    wide: { type: Boolean, default: false },
  },
  template: `
    <div :class="['info-card', wide ? 'wide' : '']">
      <div class="info-label">{{ label }}</div>
      <div class="info-value">{{ value }}</div>
    </div>
  `,
};

export const ThemeSwitcher = {
  props: {
    theme: String,
  },
  emits: ["change"],
  setup() {
    return { THEMES, icons };
  },
  template: `
    <div class="theme-switcher">
      <button
        v-for="item in THEMES"
        :key="item.id"
        type="button"
        :class="['theme-chip', theme === item.id ? 'is-active' : '']"
        @click="$emit('change', item.id)"
      >
        <component :is="icons[item.icon]" class="h-4 w-4" />
        <span>{{ item.label }}</span>
      </button>
    </div>
  `,
};

export const ArtifactCardList = {
  props: {
    files: { type: Array, default: () => [] },
    compact: { type: Boolean, default: false },
    userUpload: { type: Boolean, default: false },
    openLabel: { type: String, default: "点击预览" },
  },
  emits: ["open"],
  setup() {
    return { formatFileSize, formatUtc8Timestamp, iconNameForArtifact, icons };
  },
  methods: {
    artifactIcon(file) {
      return icons[iconNameForArtifact(file)] || icons.FileText;
    },
    handleOpen(file) {
      this.$emit("open", file);
    },
  },
  template: `
    <div :class="[compact ? 'artifact-grid artifact-grid-compact is-user-upload-compact' : 'artifact-grid']">
      <article
        v-for="file in files"
        :key="file.id || file.path || file.name"
        :class="['artifact-card', userUpload ? 'is-user-upload' : '', compact ? 'is-compact' : '']"
      >
        <button
          type="button"
          class="artifact-card-main"
          :disabled="!file.preview_url && !file.download_url"
          @click="handleOpen(file)"
        >
          <div class="artifact-icon-wrap">
            <component :is="artifactIcon(file)" class="h-4 w-4" />
          </div>
          <div class="artifact-card-head">
            <div class="artifact-title">{{ file.original_name || file.name || file.title }}</div>
            <span class="tag artifact-ext-tag">{{ file.extension || '(无后缀)' }}</span>
          </div>
          <div class="artifact-meta">{{ formatFileSize(file.size) }} · {{ formatUtc8Timestamp(file.updated_at) }}</div>
          <div v-if="userUpload && !compact && file.path" class="artifact-path">{{ file.path }}</div>
        </button>
        <div v-if="!userUpload" class="artifact-actions">
          <span class="artifact-open-hint">{{ openLabel }}</span>
          <a :href="file.download_url" class="secondary-button compact artifact-download" download>下载</a>
        </div>
      </article>
    </div>
  `,
};

export const PendingUploadList = {
  props: {
    files: { type: Array, default: () => [] },
  },
  emits: ["remove"],
  setup() {
    return { formatFileSize, iconNameForArtifact, pendingUploadTone, icons };
  },
  methods: {
    artifactIcon(file) {
      return icons[iconNameForArtifact(file)] || icons.FileText;
    },
    toneClass(status) {
      return pendingUploadTone(status);
    },
  },
  template: `
    <div class="pending-upload-grid">
      <div v-for="file in files" :key="file.id" class="pending-upload-card is-compact">
        <div class="pending-upload-main">
          <div class="artifact-icon-wrap">
            <component :is="artifactIcon(file)" class="h-4 w-4" />
          </div>
          <div class="pending-upload-copy">
            <div class="pending-upload-title">{{ file.name }}</div>
            <div class="pending-upload-meta">{{ formatFileSize(file.size) }} · {{ file.extension }}</div>
          </div>
          <button type="button" class="icon-button" aria-label="移除文件" @click="$emit('remove', file.id)">
            <component :is="icons.Trash2" class="h-4 w-4" />
          </button>
        </div>
        <div :class="['upload-progress-track', file.status === 'ready' ? 'is-ready' : file.status === 'error' ? 'is-error' : '']">
          <span class="upload-progress-fill" :style="{ width: (file.progress || 0) + '%' }"></span>
        </div>
        <div class="pending-upload-foot">
          <div class="pending-upload-meta">
            {{ file.status === 'ready' ? '已上传，待发送' : file.status === 'error' ? (file.error || '上传失败') : '上传中' }}
          </div>
          <div class="pending-upload-percent">{{ Math.round(file.progress || 0) }}%</div>
        </div>
      </div>
    </div>
  `,
};
