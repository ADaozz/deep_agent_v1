import { computed, nextTick, onMounted, ref, watch } from "vue";
import { marked } from "marked";
import DOMPurify from "dompurify";

import { icons } from "../icons.js";
import {
  classifyArtifact,
  formatFileSize,
  formatUtc8Timestamp,
  iconNameForArtifact,
  isActiveWorkerStatus,
  statusClass,
  stepLabel,
  stepState,
  toSpreadsheetColumnName,
} from "../utils.js";
import {
  ArtifactCardList,
  ChatBubble,
  EmptyHint,
  IconForStep,
  SectionTitle,
} from "./common.js";

let mermaidReady = false;
let mermaidModulePromise = null;

async function loadMermaid() {
  if (!mermaidModulePromise) {
    mermaidModulePromise = import("mermaid").then((module) => module.default || module);
  }
  return mermaidModulePromise;
}

export const TodoList = {
  components: { IconForStep },
  props: {
    todos: { type: Array, default: () => [] },
  },
  setup() {
    return { statusClass, stepLabel };
  },
  template: `
    <div v-if="todos.length" class="stack-block">
      <div v-for="(todo, index) in todos" :key="todo.id || todo.label || index" :class="['todo-card', statusClass(todo.status)]">
        <div class="todo-head">
          <div class="todo-title">
            <IconForStep :status="todo.status" :compact="true" />
            <span>{{ todo.label || '未命名待办' }}</span>
          </div>
          <span :class="['tag', statusClass(todo.status)]">{{ stepLabel(todo.status) }}</span>
        </div>
        <div class="todo-note">{{ todo.note || '等待该 worker 填写说明。' }}</div>
        <div class="evidence-box">
          <span class="evidence-label">Evidence</span>
          <div>{{ todo.result || '尚未提供 evidence。' }}</div>
        </div>
      </div>
    </div>
  `,
};

export const TaskList = {
  components: { IconForStep },
  props: {
    tasks: { type: Array, default: () => [] },
  },
  setup() {
    return { statusClass, stepLabel };
  },
  template: `
    <div v-if="!tasks.length" class="empty-block">Action List 会在 Supervisor 完成任务原子化后出现。</div>
    <div v-else class="stack-block">
      <div
        v-for="(task, index) in tasks"
        :key="task.id || task.title || index"
        :class="['timeline-card', statusClass(task.status)]"
      >
        <div class="timeline-rail">
          <IconForStep :status="task.status" />
          <div v-if="index < tasks.length - 1" class="timeline-line"></div>
        </div>
        <div class="timeline-content">
          <div class="timeline-header">
            <div>
              <div class="timeline-title">{{ task.title || task.id || '未命名任务' }}</div>
              <div class="timeline-desc">{{ task.detail || task.summary || '等待 Supervisor 分配更具体的执行说明。' }}</div>
            </div>
            <div class="timeline-side">
              <span :class="['tag', statusClass(task.status)]">{{ stepLabel(task.status) }}</span>
              <span>{{ task.owner || 'Supervisor' }} · Round {{ task.last_round || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};

export const RoundList = {
  props: {
    rounds: { type: Array, default: () => [] },
  },
  setup() {
    return { statusClass, stepLabel, stepState, icons };
  },
  template: `
    <div v-if="!rounds.length" class="empty-block">每个执行周期都会在这里以会话消息形式展开。</div>
    <div v-else class="stack-block">
      <details
        v-for="(round, index) in [...rounds].sort((a, b) => (a.index || 0) - (b.index || 0))"
        :key="round.index || index"
        :class="['disclosure-card', statusClass(round.status || (round.conclusion ? 'done' : 'running'))]"
        :open="stepState(round.status || (round.conclusion ? 'done' : 'running')) !== 'success'"
      >
        <summary>
          <div>
            <div class="summary-title">Round {{ round.index }}</div>
            <div class="summary-subtitle">{{ round.thought || '等待本轮说明。' }}</div>
          </div>
          <div class="summary-tail">
            <span :class="['tag', statusClass(round.status || (round.conclusion ? 'done' : 'running'))]">
              {{ stepLabel(round.status || (round.conclusion ? 'done' : 'running')) }}
            </span>
            <component :is="icons.ChevronDown" class="h-4 w-4 disclosure-icon" />
          </div>
        </summary>
        <div class="disclosure-body">
          <div v-if="(round.dispatches || []).length" class="stack-block">
            <div v-for="(dispatch, dispatchIndex) in (round.dispatches || [])" :key="(round.index || index) + '-' + dispatchIndex" class="inline-log">
              {{ dispatch }}
            </div>
          </div>
          <div v-else class="empty-block">本轮没有 dispatch 记录。</div>
          <div class="note-block">{{ round.conclusion || '等待本轮收敛结论。' }}</div>
        </div>
      </details>
    </div>
  `,
};

export const WorkerList = {
  components: { TodoList, IconForStep },
  emits: ["open"],
  props: {
    agents: { type: Array, default: () => [] },
  },
  setup() {
    return { stepState, statusClass, stepLabel, icons };
  },
  template: `
    <div v-if="!agents.length" class="empty-block">当前没有活跃 worker。</div>
    <div v-else class="stack-block">
      <details
        v-for="agent in agents"
        :key="agent.id || agent.name"
        :class="['disclosure-card', statusClass(agent.status)]"
        :open="stepState(agent.status) === 'success' ? false : Boolean(agent.todo_list?.length || agent.status === 'running' || agent.status === 'blocked' || stepState(agent.status) === 'error' || agent.report || agent.last_guard_message)"
      >
        <summary>
          <div class="worker-summary">
            <button type="button" class="worker-avatar" title="查看 Agent metadata" @click.prevent="$emit('open', agent)">
              <component :is="icons.Bot" class="h-4 w-4" />
            </button>
            <div>
              <div class="summary-title">{{ agent.name }}</div>
              <div class="summary-subtitle">{{ agent.role || '未定义角色' }} · {{ agent.current_task_title || '待命中' }}</div>
            </div>
          </div>
          <div class="summary-tail">
            <span :class="['tag', statusClass(agent.status)]">{{ stepLabel(agent.status) }}</span>
            <component :is="icons.ChevronDown" class="h-4 w-4 disclosure-icon" />
          </div>
        </summary>
        <div class="disclosure-body">
          <div class="detail-grid worker-metric-grid">
            <div class="metric-card">
              <span class="metric-label">Checklist</span>
              <span class="metric-value">
                {{
                  agent.todo_list?.length
                    ? String(agent.todo_list.length)
                    : stepState(agent.status) === 'running'
                      ? '同步中'
                      : stepState(agent.status) === 'blocked'
                        ? '阻塞'
                        : stepState(agent.status) === 'error'
                          ? '异常'
                          : '0'
                }}
              </span>
            </div>
            <div class="metric-card">
              <span class="metric-label">Runtime guard</span>
              <span class="metric-value">
                {{
                  agent.last_guard_message
                    ? '已拦截 ' + Math.max(agent.guard_hits || 1, 1) + ' 次'
                    : agent.status === 'blocked'
                      ? '已阻塞'
                      : stepState(agent.status) === 'error'
                        ? '执行失败'
                        : '正常'
                }}
              </span>
            </div>
            <div class="metric-card">
              <span class="metric-label">Scope</span>
              <span class="metric-value">{{ agent.scope || agent.role || agent.description || '未定义边界' }}</span>
            </div>
          </div>
          <div :class="stepState(agent.status) === 'error' || stepState(agent.status) === 'blocked' ? 'alert-block' : 'note-block'">
            {{ agent.report || '本轮尚未汇报。' }}
          </div>
          <div v-if="agent.last_guard_message" class="alert-block">{{ agent.last_guard_message }}</div>
          <TodoList :todos="agent.todo_list || []" />
        </div>
      </details>
    </div>
  `,
};

export const LogList = {
  props: {
    logs: { type: Array, default: () => [] },
  },
  template: `
    <div v-if="!logs.length" class="empty-block">执行日志会在这里以对话内附属记录方式展示。</div>
    <div v-else class="stack-block">
      <div v-for="(log, index) in logs" :key="(log.time || 'log') + '-' + (log.source || 'source') + '-' + index" class="inline-log">
        <div class="log-meta">{{ log.time }} · {{ log.source }}</div>
        <div>{{ log.message }}</div>
      </div>
    </div>
  `,
};

export const FinalSummaryContent = {
  props: { content: String },
  setup(props) {
    const containerRef = ref(null);
    const renderedHtml = computed(() => {
      const rawHtml = marked.parse(props.content || "", { gfm: true, breaks: true });
      return DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } });
    });

    async function renderMermaid() {
      if (!containerRef.value) return;
      const mermaidBlocks = Array.from(containerRef.value.querySelectorAll("pre > code.language-mermaid"));
      if (!mermaidBlocks.length) return;
      const mermaid = await loadMermaid();
      if (!mermaidReady) {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "default",
        });
        mermaidReady = true;
      }
      for (const [index, block] of mermaidBlocks.entries()) {
        const source = block.textContent || "";
        const host = document.createElement("div");
        host.className = "mermaid-block";
        try {
          const renderId = `mermaid-${Date.now()}-${index}`;
          const { svg } = await mermaid.render(renderId, source);
          host.innerHTML = svg;
        } catch (error) {
          host.innerHTML = `<pre class="mermaid-error">${String(error?.message || error || "Mermaid render failed.")}</pre>`;
        }
        block.parentElement?.replaceWith(host);
      }
    }

    watch(renderedHtml, async () => {
      await nextTick();
      await renderMermaid();
    }, { immediate: true });

    return { containerRef, renderedHtml };
  },
  template: `<div ref="containerRef" class="final-answer-text md-content" v-html="renderedHtml"></div>`,
};

export const SpreadsheetPreview = {
  props: { data: Object },
  setup(props) {
    const activeSheetName = ref("");
    const hoverCell = ref({ row: -1, column: -1 });
    const sheets = computed(() => Array.isArray(props.data?.sheets) ? props.data.sheets : []);
    const activeSheet = computed(() => sheets.value.find((sheet) => sheet.name === activeSheetName.value) || sheets.value[0] || null);
    watch(sheets, (nextSheets) => {
      activeSheetName.value = nextSheets[0]?.name || "";
    }, { immediate: true });
    return {
      activeSheetName,
      hoverCell,
      sheets,
      activeSheet,
      toSpreadsheetColumnName,
    };
  },
  template: `
    <div v-if="activeSheet" class="spreadsheet-preview">
      <div class="spreadsheet-toolbar">
        <div class="spreadsheet-app-badge">Excel Preview</div>
        <div class="spreadsheet-meta">
          <span>{{ activeSheet.row_count || 0 }} 行</span>
          <span>{{ activeSheet.column_count || 0 }} 列</span>
          <span v-if="activeSheet.truncated_rows || activeSheet.truncated_columns">
            当前仅预览前 {{ activeSheet.preview_row_count || 0 }} 行 / {{ activeSheet.preview_column_count || 0 }} 列
          </span>
        </div>
      </div>
      <div class="spreadsheet-tabs excel-tabs">
        <button
          v-for="sheet in sheets"
          :key="sheet.name"
          type="button"
          :class="['spreadsheet-tab', sheet.name === activeSheet.name ? 'is-active' : '']"
          @click="activeSheetName = sheet.name"
        >
          {{ sheet.name }}
        </button>
      </div>
      <div class="spreadsheet-formula-bar">
        <span class="spreadsheet-name-box">{{ activeSheet.name }}</span>
        <span class="spreadsheet-fx">fx</span>
        <span class="spreadsheet-formula-text">当前为只读预览，保留 Excel 风格网格与工作表层级。</span>
      </div>
      <div class="spreadsheet-table-wrap excel-frame">
        <table class="spreadsheet-table excel-table">
          <colgroup>
            <col style="width: 56px" />
            <col
              v-for="(width, index) in (activeSheet.column_widths || [])"
              :key="'col-width-' + index"
              :style="{ width: (width || 96) + 'px' }"
            />
          </colgroup>
          <tbody>
            <tr>
              <td class="excel-corner"></td>
              <td
                v-for="index in Number(activeSheet.preview_column_count || 0)"
                :key="'header-' + index"
                :class="['excel-col-header', hoverCell.column === index - 1 ? 'is-hover-axis' : '']"
              >
                {{ toSpreadsheetColumnName(index - 1) }}
              </td>
            </tr>
            <tr v-for="(row, rowIndex) in (activeSheet.rows || [])" :key="rowIndex">
              <td :class="['excel-row-header', hoverCell.row === rowIndex ? 'is-hover-axis' : '']">{{ rowIndex + 1 }}</td>
              <td
                v-for="(cell, cellIndex) in (Array.isArray(row) ? row : [])"
                :key="rowIndex + '-' + (cell?.column ?? cellIndex)"
                :colspan="Number(cell?.colspan || 1)"
                :rowspan="Number(cell?.rowspan || 1)"
                :class="[
                  'excel-cell',
                  hoverCell.row >= rowIndex &&
                  hoverCell.row < rowIndex + Number(cell?.rowspan || 1) &&
                  hoverCell.column >= Number(cell?.column ?? cellIndex) &&
                  hoverCell.column < Number(cell?.column ?? cellIndex) + Number(cell?.colspan || 1)
                    ? 'is-hover-cell'
                    : '',
                ]"
                @mouseenter="hoverCell = { row: rowIndex, column: Number(cell?.column ?? cellIndex) }"
                @mouseleave="hoverCell = { row: -1, column: -1 }"
              >
                {{ cell?.value || '' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div v-else class="empty-block">当前 Excel 文件没有可展示的 sheet。</div>
  `,
};

export const FilePreviewContent = {
  components: { SpreadsheetPreview },
  props: {
    file: Object,
    previewState: { type: Object, default: () => ({}) },
  },
  setup(props) {
    const kind = computed(() => classifyArtifact(props.file));
    return { kind, icons, formatFileSize };
  },
  template: `
    <div v-if="!file" class="empty-block">未选择文件。</div>
    <div v-else-if="kind === 'image'" class="file-preview-shell">
      <img class="file-preview-image" :src="file.preview_url" :alt="file.title || file.name" />
    </div>
    <iframe v-else-if="kind === 'pdf'" class="file-preview-frame" :src="file.preview_url" :title="file.title || file.name"></iframe>
    <div v-else-if="previewState.loading" class="empty-block">
      <span class="loading-inline">
        <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
        <span>正在加载文件预览...</span>
      </span>
    </div>
    <div v-else-if="previewState.error" class="alert-block">{{ previewState.error }}</div>
    <div v-else-if="kind === 'markdown'" class="md-content file-preview-markdown" v-html="previewState.html || ''"></div>
    <SpreadsheetPreview v-else-if="kind === 'spreadsheet'" :data="previewState.spreadsheet" />
    <pre v-else-if="kind === 'text'" class="prompt-code-block file-preview-code"><code>{{ previewState.text || '' }}</code></pre>
    <div v-else class="stack-block">
      <div class="note-block">当前文件类型暂不支持内嵌预览，请直接下载查看。</div>
      <div class="detail-grid">
        <div class="info-card wide">
          <div class="info-label">File</div>
          <div class="info-value">{{ file.name }}</div>
        </div>
        <div class="info-card">
          <div class="info-label">Type</div>
          <div class="info-value">{{ file.extension || file.mime_type }}</div>
        </div>
        <div class="info-card">
          <div class="info-label">Size</div>
          <div class="info-value">{{ formatFileSize(file.size) }}</div>
        </div>
      </div>
    </div>
  `,
};

export const SessionTranscript = {
  components: {
    ArtifactCardList,
    ChatBubble,
    EmptyHint,
    FilePreviewContent,
    FinalSummaryContent,
    LogList,
    RoundList,
    SectionTitle,
    TaskList,
    WorkerList,
  },
  props: {
    session: { type: Object, required: true },
    error: { type: String, default: "" },
  },
  emits: ["open-agent", "open-file"],
  setup(props) {
    const state = computed(() => props.session.state || {});
    const userFiles = computed(() => Array.isArray(state.value.user_files) ? state.value.user_files : []);
    const completedCount = computed(() => (state.value.tasks || []).filter((task) => stepState(task.status) === "success").length);
    const hasWorkerActivity = computed(() => (state.value.agents || []).some(
      (agent) => agent.current_task_title || agent.report || agent.guard_hits || agent.last_guard_message || (agent.todo_list && agent.todo_list.length)
    ));
    return {
      state,
      userFiles,
      completedCount,
      hasWorkerActivity,
      stepState,
      icons,
    };
  },
  template: `
    <div class="session-thread">
      <ChatBubble title="User Query" eyebrow="Input" :icon="icons.MessageSquare" kind="user">
        <ArtifactCardList v-if="userFiles.length" :files="userFiles" :compact="true" :user-upload="true" @open="$emit('open-file', $event)" />
        <div class="user-query-text">{{ session.query }}</div>
      </ChatBubble>

      <ChatBubble v-if="(state.tasks || []).length" title="Action List" eyebrow="Execution" :icon="icons.ClipboardList">
        <SectionTitle
          :icon="icons.ClipboardList"
          title="任务追踪"
          :meta="completedCount + '/' + ((state.tasks || []).length || 0) + ' completed'"
        />
        <TaskList :tasks="state.tasks || []" />
      </ChatBubble>

      <ChatBubble v-if="hasWorkerActivity" title="Workers And Checklists" eyebrow="Collaboration" :icon="icons.Bot">
        <SectionTitle :icon="icons.Bot" title="Worker 对话与 check_list" :meta="(state.agents || []).length + ' worker(s)'" />
        <WorkerList :agents="state.agents || []" @open="$emit('open-agent', $event)" />
      </ChatBubble>

      <ChatBubble v-if="(state.rounds || []).length" title="Round Trace" eyebrow="Cycle" :icon="icons.Activity">
        <SectionTitle :icon="icons.Activity" title="Dispatch 与收敛过程" :meta="(state.rounds || []).length + ' round(s)'" />
        <RoundList :rounds="state.rounds || []" />
      </ChatBubble>

      <ChatBubble v-if="(state.logs || []).length" title="Execution Log" eyebrow="Trace" :icon="icons.ShieldAlert">
        <details class="disclosure-card log-disclosure">
          <summary>
            <SectionTitle :icon="icons.ShieldAlert" title="事件流" :meta="(state.logs || []).length + ' log(s) · 最近 60 条'" />
            <component :is="icons.ChevronDown" class="h-4 w-4 disclosure-icon" />
          </summary>
          <div class="disclosure-body">
            <LogList :logs="state.logs || []" />
          </div>
        </details>
      </ChatBubble>

      <ChatBubble
        v-if="state.final_summary || error || state.status === 'running'"
        :title="state.status === 'running' && !state.final_summary ? 'Assistant' : (error || state.status === 'stopped') ? 'Execution Error' : 'Final Summary'"
        :eyebrow="(error || state.status === 'stopped') ? 'Error' : 'Assistant'"
        :icon="state.status === 'running' && !state.final_summary ? icons.LoaderCircle : (error || state.status === 'stopped') ? icons.ShieldAlert : icons.Sparkles"
        :accent="(error || state.status === 'stopped') ? 'is-error' : ''"
      >
        <div class="final-answer-text">
          <span v-if="state.status === 'running' && !state.final_summary" class="loading-inline">
            <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
            <span>正在生成回复...</span>
          </span>
          <FinalSummaryContent v-else :content="state.final_summary || error" />
        </div>
      </ChatBubble>

      <ChatBubble v-if="(state.files || []).length" title="Workspace Files" eyebrow="Artifacts" :icon="icons.BookText">
        <SectionTitle :icon="icons.BookText" title="文件产物" :meta="(state.files || []).length + ' file(s)'" />
        <ArtifactCardList :files="state.files || []" @open="$emit('open-file', $event)" />
      </ChatBubble>
    </div>
  `,
};
