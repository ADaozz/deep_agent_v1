import { icons } from "../icons.js";
import { formatUtc8Timestamp } from "../utils.js";

export const PromptCenter = {
  props: {
    prompts: { type: Array, default: () => [] },
    activePromptId: String,
    loading: Boolean,
    error: String,
    draftContent: String,
    saveFeedback: String,
    saveFeedbackTone: String,
    saving: Boolean,
    resetting: Boolean,
    readOnly: Boolean,
  },
  emits: ["select", "update:draftContent", "save", "reset"],
  methods: {
    promptTags(prompt) {
      return Array.isArray(prompt?.tags) ? prompt.tags.filter(Boolean) : [];
    },
  },
  computed: {
    activePrompt() {
      return this.prompts.find((item) => item.id === this.activePromptId) || this.prompts[0] || null;
    },
  },
  template: `
    <div class="prompt-browser">
      <div class="prompt-nav">
        <button
          v-for="prompt in prompts"
          :key="prompt.id"
          type="button"
          :class="['prompt-nav-item', prompt.id === (activePrompt?.id || '') ? 'is-active' : '']"
          @click="$emit('select', prompt.id)"
        >
          <div class="prompt-nav-head">
            <div class="prompt-nav-title">{{ prompt.title }}</div>
            <span v-for="tag in promptTags(prompt)" :key="tag" class="tag prompt-kind-tag">{{ tag }}</span>
          </div>
          <div class="prompt-nav-subtitle">{{ prompt.subtitle }}</div>
        </button>
        <div v-if="!prompts.length" class="empty-block">当前没有可展示的提示词。</div>
      </div>
      <div class="prompt-content">
        <div v-if="loading" class="empty-block">
          <span class="loading-inline">
            <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
            <span>正在加载提示词...</span>
          </span>
        </div>
        <div v-else-if="error" class="alert-block">{{ error }}</div>
        <div v-else-if="activePrompt" class="stack-block prompt-stack">
          <div class="prompt-meta-card">
            <div>
              <div class="summary-title">{{ activePrompt.title }}</div>
              <div class="summary-subtitle">{{ activePrompt.subtitle }}</div>
            </div>
            <div class="prompt-meta-tags">
              <span v-for="tag in promptTags(activePrompt)" :key="tag" class="tag prompt-kind-tag">{{ tag }}</span>
              <span class="tag">{{ activePrompt.source }}</span>
            </div>
          </div>
          <div class="prompt-toolbar">
            <span class="prompt-toolbar-note">
              {{ readOnly ? '执行中可查看提示词，但暂不允许修改或保存。' : '修改后点击保存，后端会立即更新并影响后续运行。' }}
            </span>
            <div class="prompt-toolbar-actions">
              <button type="button" class="secondary-button" :disabled="readOnly || saving || resetting" @click="$emit('reset')">
                <component v-if="resetting" :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
                <span>{{ resetting ? '恢复中' : '恢复默认' }}</span>
              </button>
              <button type="button" class="primary-button" :disabled="readOnly || saving || resetting" @click="$emit('save')">
                <component v-if="saving" :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
                <span>{{ saving ? '保存中' : '保存提示词' }}</span>
              </button>
            </div>
          </div>
          <div v-if="saveFeedback" :class="saveFeedbackTone === 'success' ? 'success-block' : saveFeedbackTone === 'error' ? 'alert-block' : 'note-block'">
            {{ saveFeedback }}
          </div>
          <textarea
            class="field-control field-area prompt-editor"
            :value="draftContent"
            spellcheck="false"
            :readonly="readOnly"
            @input="$emit('update:draftContent', $event.target.value)"
          ></textarea>
        </div>
        <div v-else class="empty-block">请选择左侧的提示词模块。</div>
      </div>
    </div>
  `,
  setup() {
    return { icons };
  },
};

export const SkillCenter = {
  props: {
    skills: { type: Array, default: () => [] },
    activeSkillId: String,
    loading: Boolean,
    error: String,
    draftContent: String,
    saveFeedback: String,
    saveFeedbackTone: String,
    saving: Boolean,
    resetting: Boolean,
    readOnly: Boolean,
  },
  emits: ["select", "update:draftContent", "save", "reset"],
  methods: {
    skillDisplayName(skill) {
      const frontmatterName = typeof skill?.frontmatter?.name === "string" ? skill.frontmatter.name.trim() : "";
      return frontmatterName || skill?.id || "";
    },
    scopeLabel(skill) {
      if (skill?.skill_scope === "supervisor") return "Supervisor Skill";
      if (skill?.skill_scope === "worker") return "Worker Skill";
      return "Skill";
    },
    renderFrontmatterValue(value) {
      if (Array.isArray(value)) return value.join(", ");
      if (value && typeof value === "object") return JSON.stringify(value, null, 2);
      return String(value ?? "");
    },
  },
  computed: {
    activeSkill() {
      return this.skills.find((item) => item.id === this.activeSkillId) || this.skills[0] || null;
    },
  },
  template: `
    <div class="prompt-browser">
      <div class="prompt-nav">
        <button
          v-for="skill in skills"
          :key="skill.id"
          type="button"
          :class="['prompt-nav-item', skill.id === (activeSkill?.id || '') ? 'is-active' : '']"
          @click="$emit('select', skill.id)"
        >
          <div class="prompt-nav-head">
            <div class="prompt-nav-title">{{ skillDisplayName(skill) }}</div>
            <span class="tag prompt-kind-tag is-dynamic">{{ scopeLabel(skill) }}</span>
          </div>
        </button>
        <div v-if="!skills.length" class="empty-block">当前没有可展示的 skill。</div>
      </div>
      <div class="prompt-content">
        <div v-if="loading" class="empty-block">
          <span class="loading-inline">
            <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
            <span>正在加载 skill...</span>
          </span>
        </div>
        <div v-else-if="error" class="alert-block">{{ error }}</div>
        <div v-else-if="activeSkill" class="stack-block prompt-stack">
          <div class="prompt-meta-card">
            <div>
              <div class="summary-title">{{ skillDisplayName(activeSkill) }}</div>
            </div>
            <div class="prompt-meta-tags">
              <span class="tag prompt-kind-tag is-dynamic">{{ scopeLabel(activeSkill) }}</span>
              <span class="tag">{{ activeSkill.source }}</span>
            </div>
          </div>
          <div class="prompt-toolbar">
            <span class="prompt-toolbar-note">
              {{ readOnly ? '执行中可查看 skill，但暂不允许修改或保存。' : 'skill 使用 YAML 头 + 正文结构；保存后会立即影响后续运行。' }}
            </span>
            <div class="prompt-toolbar-actions">
              <button type="button" class="secondary-button" :disabled="readOnly || saving || resetting" @click="$emit('reset')">
                <component v-if="resetting" :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
                <span>{{ resetting ? '恢复中' : '恢复默认' }}</span>
              </button>
              <button type="button" class="primary-button" :disabled="readOnly || saving || resetting" @click="$emit('save')">
                <component v-if="saving" :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
                <span>{{ saving ? '保存中' : '保存 Skill' }}</span>
              </button>
            </div>
          </div>
          <div v-if="saveFeedback" :class="saveFeedbackTone === 'success' ? 'success-block' : saveFeedbackTone === 'error' ? 'alert-block' : 'note-block'">
            {{ saveFeedback }}
          </div>
          <div class="skill-preview-grid">
            <div class="info-card wide skill-preview-card">
              <div class="info-label">YAML 头属性</div>
              <div class="skill-frontmatter-list">
                <div
                  v-for="(value, key) in (activeSkill.frontmatter || {})"
                  :key="key"
                  class="skill-frontmatter-row"
                >
                  <div class="skill-frontmatter-key">{{ key }}</div>
                  <div class="info-value preserve-lines skill-frontmatter-value">{{ renderFrontmatterValue(value) }}</div>
                </div>
                <div v-if="!Object.keys(activeSkill.frontmatter || {}).length" class="empty-block compact">当前没有 frontmatter 属性。</div>
              </div>
            </div>
          </div>
          <div class="info-label">正文编辑</div>
          <textarea
            class="field-control field-area prompt-editor"
            :value="draftContent"
            spellcheck="false"
            :readonly="readOnly"
            @input="$emit('update:draftContent', $event.target.value)"
          ></textarea>
        </div>
        <div v-else class="empty-block">请选择左侧的 skill 模块。</div>
      </div>
    </div>
  `,
  setup() {
    return { icons };
  },
};

export const HistoryCenter = {
  props: {
    threads: { type: Array, default: () => [] },
    activeThreadId: String,
    deletingThreadId: String,
    loading: Boolean,
    error: String,
    interactionLocked: Boolean,
  },
  emits: ["select-thread", "delete-thread"],
  template: `
    <div class="history-center-shell">
      <div v-if="loading" class="empty-block">
        <span class="loading-inline">
          <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
          <span>正在加载历史会话...</span>
        </span>
      </div>
      <div v-else-if="error" class="alert-block">{{ error }}</div>
      <div v-else-if="!threads.length" class="empty-block">当前还没有已持久化的历史线程。</div>
      <div v-else class="history-thread-list">
        <div
          v-for="thread in threads"
          :key="thread.thread_id"
          :class="['history-thread-card', thread.thread_id === activeThreadId ? 'is-active' : '']"
        >
          <button
            type="button"
            class="history-thread-main"
            :disabled="interactionLocked"
            @click="$emit('select-thread', thread.thread_id)"
          >
            <div class="history-thread-head">
              <div class="history-thread-title">{{ thread.thread_id }}</div>
              <span class="tag">{{ thread.session_count }} 条</span>
            </div>
            <div class="history-thread-query">{{ thread.latest_query || '无最近问题摘要' }}</div>
            <div class="history-thread-meta">{{ formatUtc8Timestamp(thread.updated_at) }}</div>
          </button>
          <button
            type="button"
            class="icon-button history-thread-delete"
            aria-label="删除历史线程"
            title="删除历史线程"
            :disabled="interactionLocked || deletingThreadId === thread.thread_id"
            @click.stop="$emit('delete-thread', thread.thread_id)"
          >
            <component :is="deletingThreadId === thread.thread_id ? icons.LoaderCircle : icons.Trash2" class="h-4 w-4" :class="{ 'animate-spin': deletingThreadId === thread.thread_id }" />
          </button>
        </div>
      </div>
    </div>
  `,
  setup() {
    return { icons, formatUtc8Timestamp };
  },
};

export const ToolCenter = {
  props: {
    tools: { type: Array, default: () => [] },
    activeToolId: String,
    togglingToolId: String,
    loading: Boolean,
    error: String,
    saveFeedback: String,
    saveFeedbackTone: String,
  },
  emits: ["select", "toggle"],
  computed: {
    activeTool() {
      return this.tools.find((item) => item.id === this.activeToolId) || this.tools[0] || null;
    },
  },
  template: `
    <div class="prompt-browser">
      <div class="prompt-nav">
        <div v-for="tool in tools" :key="tool.id" :class="['tool-nav-card', tool.id === (activeTool?.id || '') ? 'is-active' : '']">
          <button type="button" class="tool-nav-main" @click="$emit('select', tool.id)">
            <div class="tool-nav-head">
              <div>
                <div class="prompt-nav-title">{{ tool.title }}</div>
                <div class="prompt-nav-subtitle">{{ tool.subtitle }}</div>
              </div>
              <span class="tag">{{ tool.scope }}</span>
            </div>
          </button>
          <div class="tool-nav-actions">
            <button
              v-if="tool.switchable"
              type="button"
              :class="['tool-switch', tool.enabled ? 'is-on' : 'is-off']"
              :disabled="togglingToolId === tool.id"
              :aria-pressed="tool.enabled"
              @click="$emit('toggle', tool.id, !tool.enabled)"
            >
              <span class="tool-switch-track"><span class="tool-switch-thumb"></span></span>
              <span>{{ togglingToolId === tool.id ? '切换中' : tool.enabled ? '已启用' : '已关闭' }}</span>
            </button>
            <span v-else class="tag">固定工具</span>
          </div>
        </div>
        <div v-if="!tools.length" class="empty-block">当前没有可展示的扩展工具。</div>
      </div>
      <div class="prompt-content tool-content">
        <div v-if="loading" class="empty-block">
          <span class="loading-inline">
            <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
            <span>正在加载工具定义...</span>
          </span>
        </div>
        <div v-else-if="error" class="alert-block">{{ error }}</div>
        <div v-else-if="activeTool" class="stack-block prompt-stack tool-stack">
          <div class="prompt-meta-card">
            <div>
              <div class="summary-title">{{ activeTool.title }}</div>
              <div class="summary-subtitle">{{ activeTool.subtitle }}</div>
            </div>
            <span class="tag">{{ activeTool.switchable ? (activeTool.enabled ? 'enabled' : 'disabled') : 'pinned' }}</span>
          </div>
          <div class="detail-grid">
            <div class="info-card">
              <div class="info-label">作用域</div>
              <div class="info-value">{{ activeTool.scope }}</div>
            </div>
            <div class="info-card">
              <div class="info-label">入口函数</div>
              <div class="info-value">{{ activeTool.function_name }}</div>
            </div>
            <div class="info-card wide">
              <div class="info-label">源码位置</div>
              <div class="info-value">{{ activeTool.source_path }}</div>
            </div>
            <div class="info-card wide">
              <div class="info-label">摘要</div>
              <div class="info-value">{{ activeTool.summary }}</div>
            </div>
            <div class="info-card wide">
              <div class="info-label">Docstring</div>
              <div class="tool-docstring">{{ activeTool.docstring || '该工具未提供 docstring。' }}</div>
            </div>
          </div>
          <div class="prompt-toolbar">
            <span class="prompt-toolbar-note">
              固定工具置顶展示且不可关闭；自定义工具来自 app/tools/custom_tools.py 中被 @tool 修饰的函数。
            </span>
          </div>
          <div v-if="saveFeedback" :class="saveFeedbackTone === 'success' ? 'success-block' : 'alert-block'">{{ saveFeedback }}</div>
        </div>
        <div v-else class="empty-block">请选择左侧的工具查看详情。</div>
      </div>
    </div>
  `,
  setup() {
    return { icons };
  },
};
