import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";
import { marked } from "marked";
import DOMPurify from "dompurify";
import mermaid from "mermaid";
import {
  Activity,
  FileCode2,
  FileSpreadsheet,
  FileText,
  ArrowUp,
  Bot,
  BookText,
  Clock3,
  CheckCircle2,
  ChevronDown,
  Circle,
  ClipboardList,
  Contrast,
  LoaderCircle,
  MessageSquare,
  MonitorCog,
  ShieldAlert,
  Sparkles,
  Square,
  TerminalSquare,
  Trash2,
  Plus,
  X,
  XCircle,
} from "lucide-react";

const html = htm.bind(React.createElement);
let mermaidReady = false;

const MAX_ROUNDS = 12;
const DEFAULT_THEME = "vscode-light";
const DEFAULT_QUERY = "";
const MAX_USER_FILE_SIZE = 10 * 1024;
const MAX_USER_FILE_COUNT = 3;
const ALLOWED_USER_FILE_EXTENSIONS = [".md", ".xlsx", ".csv", ".txt", ".py"];
const LAST_THREAD_STORAGE_KEY = "demo-last-thread-id";
const HISTORY_CACHE_PREFIX = "demo-history-cache:";
const SESSION_USER_FILES_CACHE_PREFIX = "demo-session-user-files:";

const THEMES = [
  { id: "vscode-light", label: "VS Code Light", icon: MonitorCog },
  { id: "vscode-hc", label: "High Contrast", icon: Contrast },
];

const EMPTY_STATE = {
  query: DEFAULT_QUERY,
  max_rounds: MAX_ROUNDS,
  status: "idle",
  current_round: 0,
  scheduler_thought: "等待 query 进入。Supervisor 将先做任务原子化，再决定派发哪些 worker。",
  stop_reason: "",
  final_summary: "",
  tasks: [],
  rounds: [],
  agents: [],
  files: [],
  user_files: [],
  logs: [],
};

const DEFAULT_UI_STATE = {
  theme: DEFAULT_THEME,
  query: DEFAULT_QUERY,
  showPromptModal: false,
  showHistoryModal: false,
  showArtifactModal: false,
  activePromptId: "",
  promptDraft: "",
  selectedAgentId: "",
  activeArtifactPath: "",
};

const EMPTY_DELETE_CONFIRM = {
  open: false,
  threadId: "",
};

function createThreadId() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return `thread_${stamp}_${suffix}`;
}

function normalizeUiState(snapshot = {}) {
  const nextTheme = typeof snapshot.theme === "string" ? snapshot.theme : DEFAULT_UI_STATE.theme;
  const normalizedTheme = THEMES.some((item) => item.id === nextTheme) ? nextTheme : DEFAULT_UI_STATE.theme;
  return {
    theme: normalizedTheme,
    query: typeof snapshot.query === "string" ? snapshot.query : DEFAULT_UI_STATE.query,
    showPromptModal:
      typeof snapshot.showPromptModal === "boolean"
        ? snapshot.showPromptModal
        : typeof snapshot.show_prompt_modal === "boolean"
          ? snapshot.show_prompt_modal
          : DEFAULT_UI_STATE.showPromptModal,
    showHistoryModal:
      typeof snapshot.showHistoryModal === "boolean"
        ? snapshot.showHistoryModal
        : typeof snapshot.show_history_modal === "boolean"
          ? snapshot.show_history_modal
          : DEFAULT_UI_STATE.showHistoryModal,
    showArtifactModal:
      typeof snapshot.showArtifactModal === "boolean"
        ? snapshot.showArtifactModal
        : typeof snapshot.show_artifact_modal === "boolean"
          ? snapshot.show_artifact_modal
          : DEFAULT_UI_STATE.showArtifactModal,
    activePromptId:
      typeof snapshot.activePromptId === "string"
        ? snapshot.activePromptId
        : typeof snapshot.active_prompt_id === "string"
          ? snapshot.active_prompt_id
          : DEFAULT_UI_STATE.activePromptId,
    promptDraft:
      typeof snapshot.promptDraft === "string"
        ? snapshot.promptDraft
        : typeof snapshot.prompt_draft === "string"
          ? snapshot.prompt_draft
          : DEFAULT_UI_STATE.promptDraft,
    selectedAgentId:
      typeof snapshot.selectedAgentId === "string"
        ? snapshot.selectedAgentId
        : typeof snapshot.selected_agent_id === "string"
          ? snapshot.selected_agent_id
          : DEFAULT_UI_STATE.selectedAgentId,
    activeArtifactPath:
      typeof snapshot.activeArtifactPath === "string"
        ? snapshot.activeArtifactPath
        : typeof snapshot.active_artifact_path === "string"
          ? snapshot.active_artifact_path
          : DEFAULT_UI_STATE.activeArtifactPath,
  };
}

function buildUiStateSnapshot(uiState) {
  const normalized = normalizeUiState(uiState);
  return {
    theme: normalized.theme,
    query: normalized.query,
    showPromptModal: false,
    showHistoryModal: false,
    showArtifactModal: false,
    activePromptId: normalized.activePromptId,
    promptDraft: normalized.promptDraft,
    selectedAgentId: normalized.selectedAgentId,
    activeArtifactPath: normalized.activeArtifactPath,
  };
}

function cloneBaseState() {
  return {
    ...EMPTY_STATE,
    tasks: [],
    rounds: [],
    agents: [],
    files: [],
    user_files: [],
    logs: [],
  };
}

function fileExtension(name = "") {
  const match = String(name).toLowerCase().match(/(\.[^.]+)$/);
  return match ? match[1] : "";
}

function normalizeSessionState(snapshot = {}) {
  return {
    ...cloneBaseState(),
    ...(snapshot || {}),
    tasks: Array.isArray(snapshot?.tasks) ? snapshot.tasks : [],
    rounds: Array.isArray(snapshot?.rounds) ? snapshot.rounds : [],
    agents: Array.isArray(snapshot?.agents) ? snapshot.agents : [],
    files: Array.isArray(snapshot?.files) ? snapshot.files : [],
    user_files: Array.isArray(snapshot?.user_files) ? snapshot.user_files : [],
    logs: Array.isArray(snapshot?.logs) ? snapshot.logs : [],
  };
}

function mergeSessionState(existingState, nextState) {
  const normalizedNext = normalizeSessionState(nextState);
  const preservedUserFiles =
    Array.isArray(existingState?.user_files) && existingState.user_files.length && !normalizedNext.user_files.length
      ? existingState.user_files
      : normalizedNext.user_files;
  return {
    ...normalizedNext,
    user_files: preservedUserFiles,
  };
}

function historyCacheKey(threadId) {
  return `${HISTORY_CACHE_PREFIX}${threadId}`;
}

function sessionUserFilesCacheKey(threadId, sessionId) {
  return `${SESSION_USER_FILES_CACHE_PREFIX}${threadId}:${sessionId}`;
}

function sanitizeUserFiles(files = []) {
  if (!Array.isArray(files)) return [];
  return files
    .filter((file) => file && typeof file === "object")
    .map((file) => ({
      id: file.id || "",
      path: file.path || "",
      name: file.name || "",
      title: file.title || "",
      extension: file.extension || "",
      size: typeof file.size === "number" ? file.size : 0,
      updated_at: file.updated_at || "",
      mime_type: file.mime_type || "",
      preview_url: file.preview_url || "",
      preview_json_url: file.preview_json_url || "",
      download_url: file.download_url || "",
      original_name: file.original_name || file.name || "",
      source: file.source || "user_upload",
    }));
}

function readCachedSessionUserFiles(threadId, sessionId) {
  if (!threadId || !sessionId) return [];
  try {
    const raw = window.localStorage.getItem(sessionUserFilesCacheKey(threadId, sessionId));
    if (!raw) return [];
    return sanitizeUserFiles(JSON.parse(raw));
  } catch {
    return [];
  }
}

function writeCachedSessionUserFiles(threadId, sessionId, userFiles) {
  if (!threadId || !sessionId) return;
  try {
    const sanitized = sanitizeUserFiles(userFiles);
    if (!sanitized.length) return;
    window.localStorage.setItem(sessionUserFilesCacheKey(threadId, sessionId), JSON.stringify(sanitized));
  } catch {
    return;
  }
}

function removeCachedSessionUserFilesForThread(threadId) {
  if (!threadId) return;
  try {
    const prefix = `${SESSION_USER_FILES_CACHE_PREFIX}${threadId}:`;
    for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
      const key = window.localStorage.key(index);
      if (key && key.startsWith(prefix)) {
        window.localStorage.removeItem(key);
      }
    }
  } catch {
    return;
  }
}

function hydrateSessionUserFiles(threadId, session) {
  const localUserFiles = readCachedSessionUserFiles(threadId, session.id);
  if (!localUserFiles.length) return session;
  return {
    ...session,
    state: mergeSessionState({ ...session.state, user_files: localUserFiles }, session.state),
  };
}

function sanitizeHistorySessions(sessions = []) {
  return sessions.map((session) => ({
    id: session.id,
    query: session.query || "",
    state: normalizeSessionState(session.state),
    error: session.error || "",
  }));
}

function readCachedThreadHistory(threadId) {
  if (!threadId) return [];
  try {
    const raw = window.localStorage.getItem(historyCacheKey(threadId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? sanitizeHistorySessions(parsed) : [];
  } catch {
    return [];
  }
}

function writeCachedThreadHistory(threadId, sessions) {
  if (!threadId) return;
  try {
    const sanitized = sanitizeHistorySessions(sessions);
    window.localStorage.setItem(historyCacheKey(threadId), JSON.stringify(sanitized));
    for (const session of sanitized) {
      writeCachedSessionUserFiles(threadId, session.id, session.state?.user_files || []);
    }
  } catch {
    return;
  }
}

function validatePendingUserFile(file) {
  if (!file) return "请选择文件。";
  const extension = fileExtension(file.name);
  if (!ALLOWED_USER_FILE_EXTENSIONS.includes(extension)) {
    return `仅支持 ${ALLOWED_USER_FILE_EXTENSIONS.join(", ")} 文件。`;
  }
  if (file.size > MAX_USER_FILE_SIZE) {
    return `文件不能超过 ${formatFileSize(MAX_USER_FILE_SIZE)}。`;
  }
  return "";
}

function createPendingUserFile(file) {
  return {
    id: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    file,
    name: file.name,
    title: file.name,
    extension: fileExtension(file.name),
    size: file.size,
    updated_at: new Date().toISOString(),
    mime_type: file.type || "application/octet-stream",
    status: "queued",
    progress: 0,
    source: "user_upload",
  };
}

function pendingUploadTone(status) {
  if (status === "error") return "is-error";
  if (status === "ready") return "is-ready";
  return "is-uploading";
}

function formatUtc8Timestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatFileSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function classifyArtifact(file) {
  const mimeType = (file?.mime_type || "").toLowerCase();
  const extension = (file?.extension || "").toLowerCase();
  const path = (file?.path || file?.name || "").toLowerCase();
  if ([".xlsx", ".xls", ".csv"].includes(extension)) return "spreadsheet";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType === "application/pdf" || path.endsWith(".pdf")) return "pdf";
  if (
    mimeType.startsWith("text/") ||
    mimeType.includes("json") ||
    mimeType.includes("xml") ||
    mimeType.includes("yaml") ||
    mimeType.includes("javascript") ||
    mimeType.includes("markdown") ||
    mimeType.includes("csv") ||
    /\.(md|txt|log|py|js|ts|tsx|jsx|json|ya?ml|toml|ini|cfg|conf|csv|sql|sh)$/i.test(path)
  ) {
    return path.endsWith(".md") || mimeType.includes("markdown") ? "markdown" : "text";
  }
  return "binary";
}

function iconForArtifact(file) {
  const extension = (file?.extension || "").toLowerCase();
  if ([".xlsx", ".xls", ".csv"].includes(extension)) return FileSpreadsheet;
  if ([".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".sql", ".sh"].includes(extension)) {
    return FileCode2;
  }
  return FileText;
}

function normalizeAgent(agent, existing = {}) {
  return {
    id: agent.id,
    name: agent.name || existing.name || agent.id,
    role: agent.role || existing.role || "",
    description: agent.description || existing.description || "",
    status: agent.status || existing.status || "idle",
    current_task_title: agent.current_task_title || existing.current_task_title || "",
    report: agent.report || existing.report || "",
    todo_list: agent.todo_list || existing.todo_list || [],
    completed_rounds: agent.completed_rounds ?? existing.completed_rounds ?? 0,
    guard_hits: agent.guard_hits ?? existing.guard_hits ?? 0,
    last_guard_message: agent.last_guard_message || existing.last_guard_message || "",
  };
}

function stepState(status) {
  if (status === "blocked") return "blocked";
  if (status === "running" || status === "in_progress") return "running";
  if (status === "done" || status === "completed" || status === "success") return "success";
  if (status === "error" || status === "failed") return "error";
  return "pending";
}

function stepLabel(status) {
  if (status === "blocked") return "已阻塞";
  const value = stepState(status);
  if (value === "running") return "进行中";
  if (value === "success") return "已完成";
  if (value === "error") return "错误";
  return "待处理";
}

function statusClass(status) {
  const value = stepState(status);
  if (value === "blocked") return "is-blocked";
  if (value === "running") return "is-running";
  if (value === "success") return "is-success";
  if (value === "error") return "is-error";
  return "is-pending";
}

function isActiveWorkerStatus(status) {
  return ["pending", "running", "in_progress", "blocked"].includes(status);
}

function IconForStep({ status, compact = false }) {
  const value = stepState(status);
  const size = compact ? "h-3.5 w-3.5" : "h-4 w-4";
  if (value === "blocked") {
    return html`<span className="status-icon is-blocked">
      <${ShieldAlert} className=${size} />
    </span>`;
  }
  if (value === "running") {
    return html`<span className="status-icon is-running">
      <${LoaderCircle} className=${`${size} animate-spin`} />
    </span>`;
  }
  if (value === "success") {
    return html`<span className="status-icon is-success step-pop">
      <${CheckCircle2} className=${size} />
    </span>`;
  }
  if (value === "error") {
    return html`<span className="status-icon is-error">
      <${XCircle} className=${size} />
    </span>`;
  }
  return html`<span className="status-icon is-pending">
    <${Circle} className=${size} />
  </span>`;
}

function SectionTitle({ icon: Icon, title, meta }) {
  return html`<div className="message-section-title">
    <div className="message-section-heading">
      <${Icon} className="h-4 w-4" />
      <span>${title}</span>
    </div>
    ${meta ? html`<span className="message-section-meta">${meta}</span>` : null}
  </div>`;
}

function TaskList({ tasks }) {
  if (!tasks.length) {
    return html`<div className="empty-block">Action List 会在 Supervisor 完成任务原子化后出现。</div>`;
  }

  return html`<div className="stack-block">
    ${tasks.map(
      (task, index) => html`<div key=${task.id || task.title || index} className=${`timeline-card ${statusClass(task.status)}`}>
        <div className="timeline-rail">
          <${IconForStep} status=${task.status} />
          ${index < tasks.length - 1 ? html`<div className="timeline-line"></div>` : null}
        </div>
        <div className="timeline-content">
          <div className="timeline-header">
            <div>
              <div className="timeline-title">${task.title || task.id || "未命名任务"}</div>
              <div className="timeline-desc">${task.detail || task.summary || "等待 Supervisor 分配更具体的执行说明。"}</div>
            </div>
            <div className="timeline-side">
              <span className=${`tag ${statusClass(task.status)}`}>${stepLabel(task.status)}</span>
              <span>${task.owner || "Supervisor"} · Round ${task.last_round || "-"}</span>
            </div>
          </div>
        </div>
      </div>`
    )}
  </div>`;
}

function TodoList({ todos }) {
  if (!todos.length) {
    return null;
  }

  return html`<div className="stack-block">
    ${todos.map(
      (todo, index) => html`<div key=${todo.id || todo.label || index} className=${`todo-card ${statusClass(todo.status)}`}>
        <div className="todo-head">
          <div className="todo-title">
            <${IconForStep} status=${todo.status} compact=${true} />
            <span>${todo.label || "未命名待办"}</span>
          </div>
          <span className=${`tag ${statusClass(todo.status)}`}>${stepLabel(todo.status)}</span>
        </div>
        <div className="todo-note">${todo.note || "等待该 worker 填写说明。"}</div>
        <div className="evidence-box">
          <span className="evidence-label">Evidence</span>
          <div>${todo.result || "尚未提供 evidence。"}</div>
        </div>
      </div>`
    )}
  </div>`;
}

function RoundList({ rounds }) {
  if (!rounds.length) {
    return html`<div className="empty-block">每个执行周期都会在这里以会话消息形式展开。</div>`;
  }

  const orderedRounds = [...rounds].sort((left, right) => (left.index || 0) - (right.index || 0));

  return html`<div className="stack-block">
    ${orderedRounds.map((round, index) => {
      const roundStatus = round.status || (round.conclusion ? "done" : "running");
      const shouldOpen = stepState(roundStatus) !== "success";
      return html`<details key=${round.index || index} className=${`disclosure-card ${statusClass(roundStatus)}`} open=${shouldOpen}>
        <summary>
          <div>
            <div className="summary-title">Round ${round.index}</div>
            <div className="summary-subtitle">${round.thought || "等待本轮说明。"}</div>
          </div>
          <div className="summary-tail">
            <span className=${`tag ${statusClass(roundStatus)}`}>${stepLabel(roundStatus)}</span>
            <${ChevronDown} className="h-4 w-4 disclosure-icon" />
          </div>
        </summary>
        <div className="disclosure-body">
          ${(round.dispatches || []).length
            ? html`<div className="stack-block">
                ${(round.dispatches || []).map(
                  (dispatch, dispatchIndex) => html`<div key=${`${round.index || index}-${dispatchIndex}`} className="inline-log">${dispatch}</div>`
                )}
              </div>`
            : html`<div className="empty-block">本轮没有 dispatch 记录。</div>`}
          <div className="note-block">${round.conclusion || "等待本轮收敛结论。"}</div>
        </div>
      </details>`;
    })}
  </div>`;
}

function WorkerList({ agents, onOpen }) {
  if (!agents.length) {
    return html`<div className="empty-block">当前没有活跃 worker。</div>`;
  }

  return html`<div className="stack-block">
    ${agents.map((agent) => {
      const shouldOpen =
        Boolean(agent.todo_list?.length) ||
        agent.status === "running" ||
        agent.status === "blocked" ||
        stepState(agent.status) === "error" ||
        Boolean(agent.report) ||
        Boolean(agent.last_guard_message);
      const defaultOpen = stepState(agent.status) === "success" ? false : shouldOpen;
      const todoCountText =
        agent.todo_list?.length
          ? String(agent.todo_list.length)
          : stepState(agent.status) === "running"
            ? "同步中"
            : stepState(agent.status) === "blocked"
              ? "阻塞"
            : stepState(agent.status) === "error"
              ? "异常"
              : "0";
      const guardText = agent.last_guard_message
        ? `已拦截 ${Math.max(agent.guard_hits || 1, 1)} 次`
        : agent.status === "blocked"
          ? "已阻塞"
          : stepState(agent.status) === "error"
            ? "执行失败"
            : "正常";
      const reportClass =
        stepState(agent.status) === "error" || stepState(agent.status) === "blocked" ? "alert-block" : "note-block";
      return html`<details key=${agent.id || agent.name} className=${`disclosure-card ${statusClass(agent.status)}`} open=${defaultOpen}>
        <summary>
          <div className="worker-summary">
            <button
              type="button"
              className="worker-avatar"
              onClick=${(event) => {
                event.preventDefault();
                onOpen(agent);
              }}
              title="查看 Agent metadata"
            >
              <${Bot} className="h-4 w-4" />
            </button>
            <div>
              <div className="summary-title">${agent.name}</div>
              <div className="summary-subtitle">
                ${agent.role || "未定义角色"} · ${agent.current_task_title || "待命中"}
              </div>
            </div>
          </div>
          <div className="summary-tail">
            <span className=${`tag ${statusClass(agent.status)}`}>${stepLabel(agent.status)}</span>
            <${ChevronDown} className="h-4 w-4 disclosure-icon" />
          </div>
        </summary>
        <div className="disclosure-body">
          <div className="detail-grid">
            <div className="metric-card">
              <span className="metric-label">Checklist</span>
              <span className="metric-value">${todoCountText}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Runtime guard</span>
              <span className="metric-value">${guardText}</span>
            </div>
          </div>
          <div className=${reportClass}>${agent.report || "本轮尚未汇报。"}</div>
          ${agent.last_guard_message ? html`<div className="alert-block">${agent.last_guard_message}</div>` : null}
          <${TodoList} todos=${agent.todo_list || []} />
        </div>
      </details>`;
    })}
  </div>`;
}

function PublishedFileList({ files, onOpen }) {
  if (!files.length) {
    return html`<div className="empty-block">当前没有已发布的文件产物。</div>`;
  }

  return html`<div className="artifact-grid">
    ${files.map(
      (file) => html`<article key=${file.id || file.path} className="artifact-card">
        <button type="button" className="artifact-card-main" onClick=${() => onOpen(file)}>
          <div className="artifact-icon-wrap">
            <${iconForArtifact(file)} className="h-4 w-4" />
          </div>
          <div className="artifact-card-head">
            <div className="artifact-title">${file.original_name || file.name || file.title}</div>
            <span className="tag artifact-ext-tag">${file.extension || "(无后缀)"}</span>
          </div>
          <div className="artifact-meta">${formatFileSize(file.size)} · ${formatUtc8Timestamp(file.updated_at)}</div>
        </button>
        <div className="artifact-actions">
          <span className="artifact-open-hint">点击预览</span>
          <a href=${file.download_url} className="secondary-button compact artifact-download" download>
            下载
          </a>
        </div>
      </article>`
    )}
  </div>`;
}

function UserUploadList({ files, onOpen, compact = false }) {
  if (!files.length) return null;

  return html`<div className=${compact ? "artifact-grid artifact-grid-compact is-user-upload-compact" : "artifact-grid"}>
    ${files.map(
      (file, index) => html`<article
        key=${file.id || file.path || file.name || index}
        className=${`artifact-card is-user-upload ${compact ? "is-compact" : ""}`}
      >
        <button
          type="button"
          className="artifact-card-main"
          onClick=${() => {
            if (file.preview_url || file.download_url) onOpen(file);
          }}
          disabled=${!file.preview_url && !file.download_url}
        >
          <div className="artifact-icon-wrap">
            <${iconForArtifact(file)} className="h-4 w-4" />
          </div>
          <div className="artifact-card-head">
            <div className="artifact-title">${file.original_name || file.name || file.title}</div>
            <span className="tag artifact-ext-tag">${file.extension || "(无后缀)"}</span>
          </div>
          <div className="artifact-meta">${formatFileSize(file.size)} · ${formatUtc8Timestamp(file.updated_at)}</div>
          ${compact ? null : file.path ? html`<div className="artifact-path">${file.path}</div>` : null}
        </button>
      </article>`
    )}
  </div>`;
}

function LogList({ logs }) {
  if (!logs.length) {
    return html`<div className="empty-block">执行日志会在这里以对话内附属记录方式展示。</div>`;
  }

  return html`<div className="stack-block">
    ${logs.map(
      (log, index) => html`<div key=${`${log.time || "log"}-${log.source || "source"}-${index}`} className="inline-log">
        <div className="log-meta">${log.time} · ${log.source}</div>
        <div>${log.message}</div>
      </div>`
    )}
  </div>`;
}

function ChatBubble({ kind = "assistant", title, eyebrow, icon: Icon, children, accent = "", hideHeader = false }) {
  return html`<article className=${`chat-row ${kind === "user" ? "is-user" : ""}`}>
    <div className=${`chat-bubble ${kind === "user" ? "is-user" : ""} ${accent}`}>
      ${hideHeader
        ? null
        : html`<div className="chat-bubble-head">
            <div className="chat-bubble-title">
              ${Icon ? html`<${Icon} className="h-4 w-4" />` : null}
              <span>${title}</span>
            </div>
            ${eyebrow ? html`<span className="chat-bubble-eyebrow">${eyebrow}</span>` : null}
          </div>`}
      <div className="chat-bubble-body">${children}</div>
    </div>
  </article>`;
}

function EmptyHint({ text }) {
  return html`<div className="compact-hint">${text}</div>`;
}

function FinalSummaryContent({ content }) {
  const containerRef = useRef(null);
  const renderedMarkdown = useMemo(() => {
    const rawHtml = marked.parse(content || "", {
      gfm: true,
      breaks: true,
    });
    return DOMPurify.sanitize(rawHtml, {
      USE_PROFILES: { html: true },
    });
  }, [content]);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    if (!mermaidReady) {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "default",
      });
      mermaidReady = true;
    }

    let cancelled = false;
    const mermaidBlocks = Array.from(containerRef.current.querySelectorAll("pre > code.language-mermaid"));

    async function renderMermaidBlocks() {
      for (const [index, block] of mermaidBlocks.entries()) {
        if (cancelled) return;
        const source = block.textContent || "";
        const host = document.createElement("div");
        host.className = "mermaid-block";
        try {
          const renderId = `mermaid-${Date.now()}-${index}`;
          const { svg } = await mermaid.render(renderId, source);
          if (cancelled) return;
          host.innerHTML = svg;
        } catch (error) {
          host.innerHTML = `<pre class="mermaid-error">${String(error?.message || error || "Mermaid render failed.")}</pre>`;
        }
        const pre = block.parentElement;
        pre?.replaceWith(host);
      }
    }

    void renderMermaidBlocks();
    return () => {
      cancelled = true;
    };
  }, [renderedMarkdown]);

  return html`<div
    ref=${containerRef}
    className="final-answer-text md-content"
    dangerouslySetInnerHTML=${{ __html: renderedMarkdown }}
  ></div>`;
}

function SpreadsheetPreview({ data }) {
  const sheets = Array.isArray(data?.sheets) ? data.sheets : [];
  const [activeSheetName, setActiveSheetName] = useState(() => sheets[0]?.name || "");
  const [hoverCell, setHoverCell] = useState({ row: -1, column: -1 });

  useEffect(() => {
    setActiveSheetName(sheets[0]?.name || "");
  }, [data]);

  const activeSheet = sheets.find((sheet) => sheet.name === activeSheetName) || sheets[0] || null;
  if (!activeSheet) {
    return html`<div className="empty-block">当前 Excel 文件没有可展示的 sheet。</div>`;
  }

  const rows = Array.isArray(activeSheet.rows) ? activeSheet.rows : [];
  const maxColumnCount = Number(activeSheet.preview_column_count || 0);
  const columnWidths = Array.isArray(activeSheet.column_widths) ? activeSheet.column_widths : [];

  return html`<div className="spreadsheet-preview">
    <div className="spreadsheet-toolbar">
      <div className="spreadsheet-app-badge">Excel Preview</div>
      <div className="spreadsheet-meta">
        <span>${activeSheet.row_count || 0} 行</span>
        <span>${activeSheet.column_count || 0} 列</span>
        ${
          activeSheet.truncated_rows || activeSheet.truncated_columns
            ? html`<span>当前仅预览前 ${activeSheet.preview_row_count || 0} 行 / ${activeSheet.preview_column_count || 0} 列</span>`
            : null
        }
      </div>
    </div>
    <div className="spreadsheet-tabs excel-tabs">
      ${sheets.map(
        (sheet) => html`<button
          key=${sheet.name}
          type="button"
          className=${`spreadsheet-tab ${sheet.name === activeSheet.name ? "is-active" : ""}`}
          onClick=${() => setActiveSheetName(sheet.name)}
        >
          ${sheet.name}
        </button>`
      )}
    </div>
    <div className="spreadsheet-formula-bar">
      <span className="spreadsheet-name-box">${activeSheet.name}</span>
      <span className="spreadsheet-fx">fx</span>
      <span className="spreadsheet-formula-text">当前为只读预览，保留 Excel 风格网格与工作表层级。</span>
    </div>
    <div className="spreadsheet-table-wrap excel-frame">
      <table className="spreadsheet-table excel-table">
        <colgroup>
          <col style=${{ width: "56px" }} />
          ${Array.from({ length: maxColumnCount }, (_, index) => html`<col key=${`width-${index}`} style=${{ width: `${columnWidths[index] || 96}px` }} />`)}
        </colgroup>
        <tbody>
          <tr>
            <td className="excel-corner"></td>
            ${Array.from({ length: maxColumnCount }, (_, index) => html`<td
              key=${`col-${index}`}
              className=${`excel-col-header ${hoverCell.column === index ? "is-hover-axis" : ""}`}
            >
              ${toSpreadsheetColumnName(index)}
            </td>`)}
          </tr>
          ${rows.map(
            (row, rowIndex) => html`<tr key=${rowIndex}>
              <td className=${`excel-row-header ${hoverCell.row === rowIndex ? "is-hover-axis" : ""}`}>${rowIndex + 1}</td>
              ${(Array.isArray(row) ? row : []).map((cell, cellIndex) => {
                const startColumn = Number(cell?.column ?? cellIndex);
                const colspan = Number(cell?.colspan || 1);
                const rowspan = Number(cell?.rowspan || 1);
                const isHovered =
                  hoverCell.row >= rowIndex &&
                  hoverCell.row < rowIndex + rowspan &&
                  hoverCell.column >= startColumn &&
                  hoverCell.column < startColumn + colspan;
                const crossesHover =
                  hoverCell.row === rowIndex ||
                  (hoverCell.row > rowIndex && hoverCell.row < rowIndex + rowspan) ||
                  hoverCell.column === startColumn;
                return html`<td
                  key=${`${rowIndex}-${startColumn}`}
                  className=${`excel-cell ${isHovered ? "is-hover-cell" : ""} ${crossesHover ? "is-hover-axis" : ""}`}
                  colSpan=${colspan}
                  rowSpan=${rowspan}
                  onMouseEnter=${() => setHoverCell({ row: rowIndex, column: startColumn })}
                  onMouseLeave=${() => setHoverCell({ row: -1, column: -1 })}
                >
                  ${cell?.value || ""}
                </td>`;
              })}
            </tr>`
          )}
        </tbody>
      </table>
    </div>
  </div>`;
}

function toSpreadsheetColumnName(index) {
  let current = index + 1;
  let result = "";
  while (current > 0) {
    const remainder = (current - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    current = Math.floor((current - 1) / 26);
  }
  return result;
}

function FilePreviewContent({ file, previewState }) {
  const kind = classifyArtifact(file);
  if (!file) {
    return html`<div className="empty-block">未选择文件。</div>`;
  }
  if (kind === "image") {
    return html`<div className="file-preview-shell"><img className="file-preview-image" src=${file.preview_url} alt=${file.title || file.name} /></div>`;
  }
  if (kind === "pdf") {
    return html`<iframe className="file-preview-frame" src=${file.preview_url} title=${file.title || file.name}></iframe>`;
  }
  if (previewState.loading) {
    return html`<div className="empty-block">
      <span className="loading-inline">
        <${LoaderCircle} className="h-4 w-4 animate-spin" />
        <span>正在加载文件预览...</span>
      </span>
    </div>`;
  }
  if (previewState.error) {
    return html`<div className="alert-block">${previewState.error}</div>`;
  }
  if (kind === "markdown") {
    return html`<div className="md-content file-preview-markdown" dangerouslySetInnerHTML=${{ __html: previewState.html || "" }}></div>`;
  }
  if (kind === "spreadsheet") {
    return html`<${SpreadsheetPreview} data=${previewState.spreadsheet} />`;
  }
  if (kind === "text") {
    return html`<pre className="prompt-code-block file-preview-code"><code>${previewState.text || ""}</code></pre>`;
  }
  return html`<div className="stack-block">
    <div className="note-block">当前文件类型暂不支持内嵌预览，请直接下载查看。</div>
    <div className="detail-grid">
      <div className="info-card wide">
        <div className="info-label">File</div>
        <div className="info-value">${file.name}</div>
      </div>
      <div className="info-card">
        <div className="info-label">Type</div>
        <div className="info-value">${file.extension || file.mime_type}</div>
      </div>
      <div className="info-card">
        <div className="info-label">Size</div>
        <div className="info-value">${formatFileSize(file.size)}</div>
      </div>
    </div>
  </div>`;
}

function SessionTranscript({ session, error, onOpenAgent, onOpenFile }) {
  const state = session.state;
  const userFiles = Array.isArray(state.user_files) ? state.user_files : [];
  const completedCount = state.tasks.filter((task) => stepState(task.status) === "success").length;
  const isErrorSession = Boolean(error) || state.status === "stopped";
  const errorText = error || (state.status === "stopped" ? state.stop_reason : "");
  const hasWorkerActivity = state.agents.some(
    (agent) =>
      agent.current_task_title ||
      agent.report ||
      agent.guard_hits ||
      agent.last_guard_message ||
      (agent.todo_list && agent.todo_list.length)
  );
  const showAssistantBubble = Boolean(state.final_summary || errorText) || state.status === "running";
  const showTaskBubble = state.tasks.length > 0;
  const showWorkerBubble = hasWorkerActivity;
  const showFileBubble = (state.files || []).length > 0;
  const showRoundBubble = state.rounds.length > 0;
  const showLogBubble = state.logs.length > 0;

  return html`<div className="session-thread">
    <${ChatBubble} title="User Query" eyebrow="Input" icon=${MessageSquare} kind="user">
      ${userFiles.length ? html`<${UserUploadList} files=${userFiles} onOpen=${onOpenFile} compact=${true} />` : null}
      <div className="user-query-text">${session.query}</div>
    </${ChatBubble}>

    ${
      showTaskBubble
        ? html`<${ChatBubble} title="Action List" eyebrow="Execution" icon=${ClipboardList}>
            <${SectionTitle} icon=${ClipboardList} title="任务追踪" meta=${`${completedCount}/${state.tasks.length || 0} completed`} />
            <${TaskList} tasks=${state.tasks} />
          </${ChatBubble}>`
        : null
    }

    ${
      showWorkerBubble
        ? html`<${ChatBubble} title="Workers And Checklists" eyebrow="Collaboration" icon=${Bot}>
            <${SectionTitle} icon=${Bot} title="Worker 对话与 check_list" meta=${`${state.agents.length} worker(s)`} />
            ${
              hasWorkerActivity
                ? html`<${WorkerList} agents=${state.agents} onOpen=${onOpenAgent} />`
                : html`<${EmptyHint} text="worker 已接入，等待 Supervisor 首次派发任务。" />`
            }
          </${ChatBubble}>`
        : null
    }

    ${
      showRoundBubble
        ? html`<${ChatBubble} title="Round Trace" eyebrow="Cycle" icon=${Activity}>
            <${SectionTitle} icon=${Activity} title="Dispatch 与收敛过程" meta=${`${state.rounds.length} round(s)`} />
            <${RoundList} rounds=${state.rounds} />
          </${ChatBubble}>`
        : null
    }

    ${
      showLogBubble
        ? html`<${ChatBubble} title="Execution Log" eyebrow="Trace" icon=${ShieldAlert}>
            <details className="disclosure-card log-disclosure">
              <summary>
                <${SectionTitle} icon=${ShieldAlert} title="事件流" meta=${`${state.logs.length} log(s) · 最近 60 条`} />
                <${ChevronDown} className="h-4 w-4 disclosure-icon" />
              </summary>
              <div className="disclosure-body">
                <${LogList} logs=${state.logs} />
              </div>
            </details>
          </${ChatBubble}>`
        : null
    }

    ${
      showAssistantBubble
        ? html`<${ChatBubble}
            title=${state.status === "running" && !state.final_summary ? "Assistant" : isErrorSession ? "Execution Error" : "Final Summary"}
            eyebrow=${isErrorSession ? "Error" : "Assistant"}
            icon=${state.status === "running" && !state.final_summary ? LoaderCircle : isErrorSession ? ShieldAlert : Sparkles}
            accent=${isErrorSession ? "is-error" : ""}
          >
            <div className="final-answer-text">
              ${
                state.status === "running" && !state.final_summary
                  ? html`<span className="loading-inline">
                      <${LoaderCircle} className="h-4 w-4 animate-spin" />
                      <span>正在生成回复...</span>
                    </span>`
                  : html`<${FinalSummaryContent} content=${state.final_summary || errorText} />`
              }
            </div>
            ${isErrorSession && errorText && errorText !== state.final_summary ? html`<div className="alert-block">${errorText}</div>` : null}
          </${ChatBubble}>`
        : null
    }

    ${
      showFileBubble
        ? html`<${ChatBubble} title="Workspace Files" eyebrow="Artifacts" icon=${BookText}>
            <${SectionTitle} icon=${BookText} title="文件产物" meta=${`${(state.files || []).length} file(s)`} />
            <${PublishedFileList} files=${state.files || []} onOpen=${onOpenFile} />
          </${ChatBubble}>`
        : null
    }
  </div>`;
}

function Modal({ open, title, eyebrow = "Agent Panel", children, onClose, variant = "" }) {
  if (!open) return null;

  return html`<div className="modal-root">
    <button type="button" className="modal-backdrop" aria-label="关闭" onClick=${onClose}></button>
    <div className=${`modal-card ${variant ? `is-${variant}` : ""}`}>
      <div className="modal-head">
        <div>
          <div className="modal-eyebrow">${eyebrow}</div>
          <h3 className="modal-title">${title}</h3>
        </div>
        <button type="button" onClick=${onClose} className="icon-button">
          <${X} className="h-4 w-4" />
        </button>
      </div>
      ${children}
    </div>
  </div>`;
}

function PromptCenter({
  prompts,
  activePromptId,
  onSelect,
  loading,
  error,
  draftContent,
  onDraftChange,
  onSave,
  onReset,
  saveFeedback,
  saveFeedbackTone,
  saving,
  resetting,
  readOnly = false,
}) {
  const activePrompt = prompts.find((item) => item.id === activePromptId) || prompts[0] || null;

  return html`<div className="prompt-browser">
    <div className="prompt-nav">
      ${
        prompts.length
          ? prompts.map(
              (prompt) => html`<button
                key=${prompt.id}
                type="button"
                className=${`prompt-nav-item ${prompt.id === (activePrompt?.id || "") ? "is-active" : ""}`}
                onClick=${() => onSelect(prompt.id)}
              >
                <div className="prompt-nav-title">${prompt.title}</div>
                <div className="prompt-nav-subtitle">${prompt.subtitle}</div>
              </button>`
            )
          : html`<div className="empty-block">当前没有可展示的提示词。</div>`
      }
    </div>
    <div className="prompt-content">
      ${
        loading
          ? html`<div className="empty-block">
              <span className="loading-inline">
                <${LoaderCircle} className="h-4 w-4 animate-spin" />
                <span>正在加载提示词...</span>
              </span>
            </div>`
          : error
            ? html`<div className="alert-block">${error}</div>`
            : activePrompt
              ? html`<div className="stack-block prompt-stack">
                  <div className="prompt-meta-card">
                    <div>
                      <div className="summary-title">${activePrompt.title}</div>
                      <div className="summary-subtitle">${activePrompt.subtitle}</div>
                    </div>
                    <span className="tag">${activePrompt.source}</span>
                  </div>
                  <div className="prompt-toolbar">
                    <span className="prompt-toolbar-note">
                      ${readOnly ? "执行中可查看提示词，但暂不允许修改或保存。" : "修改后点击保存，后端会立即更新并影响后续运行。"}
                    </span>
                    <div className="prompt-toolbar-actions">
                      <button type="button" className="secondary-button" onClick=${onReset} disabled=${readOnly || saving || resetting}>
                        ${resetting ? html`<${LoaderCircle} className="h-4 w-4 animate-spin" />` : null}
                        <span>${resetting ? "恢复中" : "恢复默认"}</span>
                      </button>
                      <button type="button" className="primary-button" onClick=${onSave} disabled=${readOnly || saving || resetting}>
                        ${saving ? html`<${LoaderCircle} className="h-4 w-4 animate-spin" />` : null}
                        <span>${saving ? "保存中" : "保存提示词"}</span>
                      </button>
                    </div>
                  </div>
                  ${saveFeedback ? html`<div className=${saveFeedbackTone === "success" ? "success-block" : saveFeedbackTone === "error" ? "alert-block" : "note-block"}>${saveFeedback}</div>` : null}
                  <textarea
                    className="field-control field-area prompt-editor"
                    value=${draftContent}
                    onChange=${(event) => onDraftChange(event.target.value)}
                    spellCheck="false"
                    readOnly=${readOnly}
                  ></textarea>
                </div>`
              : html`<div className="empty-block">请选择左侧的提示词模块。</div>`
      }
    </div>
  </div>`;
}

function HistoryCenter({
  threads,
  activeThreadId,
  onSelectThread,
  onDeleteThread,
  deletingThreadId,
  loading,
  error,
  interactionLocked = false,
}) {
  if (loading) {
    return html`<div className="empty-block">
      <span className="loading-inline">
        <${LoaderCircle} className="h-4 w-4 animate-spin" />
        <span>正在加载历史会话...</span>
      </span>
    </div>`;
  }

  if (error) {
    return html`<div className="alert-block">${error}</div>`;
  }

  if (!threads.length) {
    return html`<div className="empty-block">当前还没有已持久化的历史线程。</div>`;
  }

  return html`<div className="history-thread-list">
    ${threads.map(
      (thread) => html`<div
        key=${thread.thread_id}
        className=${`history-thread-card ${thread.thread_id === activeThreadId ? "is-active" : ""}`}
      >
        <button
          type="button"
          className="history-thread-main"
          onClick=${() => onSelectThread(thread.thread_id)}
          disabled=${interactionLocked}
        >
          <div className="history-thread-head">
            <div className="history-thread-title">${thread.thread_id}</div>
            <span className="tag">${thread.session_count} 条</span>
          </div>
          <div className="history-thread-query">${thread.latest_query || "无最近问题摘要"}</div>
          <div className="history-thread-meta">${formatUtc8Timestamp(thread.updated_at)}</div>
        </button>
        <button
          type="button"
          className="icon-button history-thread-delete"
          aria-label="删除历史线程"
          title="删除历史线程"
          disabled=${interactionLocked || deletingThreadId === thread.thread_id}
          onClick=${(event) => {
            event.stopPropagation();
            onDeleteThread(thread.thread_id);
          }}
        >
          ${deletingThreadId === thread.thread_id
            ? html`<${LoaderCircle} className="h-4 w-4 animate-spin" />`
            : html`<${Trash2} className="h-4 w-4" />`}
        </button>
      </div>`
    )}
  </div>`;
}

function ThemeSwitcher({ theme, setTheme }) {
  return html`<div className="theme-switcher">
    ${THEMES.map((item) => {
      const Icon = item.icon;
      return html`<button
        key=${item.id}
        type="button"
        onClick=${() => setTheme(item.id)}
        className=${`theme-chip ${theme === item.id ? "is-active" : ""}`}
      >
        <${Icon} className="h-4 w-4" />
        <span>${item.label}</span>
      </button>`;
    })}
  </div>`;
}

async function parseApiResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const rawText = await response.text();
  const normalized = rawText.trim();
  if (normalized.startsWith("<!DOCTYPE") || normalized.startsWith("<html")) {
    throw new Error("后端返回了 HTML 页面，当前服务可能还是旧版本，请重启 serve_demo.py");
  }
  throw new Error(normalized || "后端返回了非 JSON 响应");
}

function App() {
  const [demoState, setDemoState] = useState(() => cloneBaseState());
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [threadId, setThreadId] = useState(() => window.localStorage.getItem(LAST_THREAD_STORAGE_KEY) || createThreadId());
  const [modelName, setModelName] = useState("");
  const [promptSections, setPromptSections] = useState([]);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptError, setPromptError] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptResetting, setPromptResetting] = useState(false);
  const [promptSaveFeedback, setPromptSaveFeedback] = useState("");
  const [promptSaveFeedbackTone, setPromptSaveFeedbackTone] = useState("");
  const [historyThreads, setHistoryThreads] = useState([]);
  const [historyThreadsLoading, setHistoryThreadsLoading] = useState(false);
  const [historyThreadsError, setHistoryThreadsError] = useState("");
  const [deletingThreadId, setDeletingThreadId] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState(EMPTY_DELETE_CONFIRM);
  const [artifactPreview, setArtifactPreview] = useState({ loading: false, error: "", text: "", html: "", spreadsheet: null });
  const [artifactDraft, setArtifactDraft] = useState("");
  const [artifactSaving, setArtifactSaving] = useState(false);
  const [artifactSaveFeedback, setArtifactSaveFeedback] = useState("");
  const [pendingUserFiles, setPendingUserFiles] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [uiState, setUiState] = useState(() => {
    const savedTheme = window.localStorage.getItem("demo-theme");
    return normalizeUiState({
      ...DEFAULT_UI_STATE,
      theme: THEMES.some((item) => item.id === savedTheme) ? savedTheme : DEFAULT_THEME,
    });
  });
  const runControllerRef = useRef(null);
  const uploadControllersRef = useRef(new Map());
  const uiStateSaveTimerRef = useRef(null);
  const fileInputRef = useRef(null);
  const artifactSelectionRef = useRef({ path: "", originalName: "", name: "" });
  const selectedAgent = useMemo(
    () => demoState.agents.find((agent) => agent.id === uiState.selectedAgentId) || null,
    [demoState.agents, uiState.selectedAgentId]
  );
  const publishedFiles = useMemo(() => {
    const items = new Map();
    for (const session of history) {
      for (const file of session.state?.files || []) {
        if (file?.path) items.set(file.path, file);
      }
      for (const file of session.state?.user_files || []) {
        if (file?.path) items.set(file.path, file);
      }
    }
    return Array.from(items.values());
  }, [history]);
  const activeArtifact = useMemo(
    () => publishedFiles.find((file) => file.path === uiState.activeArtifactPath) || null,
    [publishedFiles, uiState.activeArtifactPath]
  );
  const activeArtifactKind = activeArtifact ? classifyArtifact(activeArtifact) : "";
  const activeArtifactPreviewKey = activeArtifact
    ? [
        activeArtifactKind,
        activeArtifact.path || "",
        activeArtifact.updated_at || "",
        activeArtifact.preview_url || "",
        activeArtifact.preview_json_url || "",
      ].join("|")
    : "";

  useEffect(() => {
    document.documentElement.dataset.theme = uiState.theme;
    window.localStorage.setItem("demo-theme", uiState.theme);
  }, [uiState.theme]);

  useEffect(() => {
    if (!threadId) return;
    window.localStorage.setItem(LAST_THREAD_STORAGE_KEY, threadId);
  }, [threadId]);

  useEffect(() => {
    if (!threadId) return;
    writeCachedThreadHistory(threadId, history);
  }, [threadId, history]);

  useEffect(() => {
    if (!uiState.showArtifactModal || activeArtifact || !uiState.activeArtifactPath) return;
    const remembered = artifactSelectionRef.current;
    const matched = publishedFiles.find(
      (file) =>
        (remembered.originalName && (file.original_name || file.name) === remembered.originalName) ||
        (remembered.name && file.name === remembered.name)
    );
    if (!matched?.path || matched.path === uiState.activeArtifactPath) return;
    setUiState((current) => normalizeUiState({ ...current, activeArtifactPath: matched.path }));
  }, [uiState.showArtifactModal, uiState.activeArtifactPath, activeArtifact, publishedFiles]);

  useEffect(() => {
    if (!uiState.showArtifactModal || !activeArtifact) {
      setArtifactPreview({ loading: false, error: "", text: "", html: "", spreadsheet: null });
      setArtifactDraft("");
      setArtifactSaveFeedback("");
      return undefined;
    }
    const kind = activeArtifactKind;
    if (!["markdown", "text", "spreadsheet"].includes(kind)) {
      setArtifactPreview({ loading: false, error: "", text: "", html: "", spreadsheet: null });
      setArtifactDraft("");
      setArtifactSaveFeedback("");
      return undefined;
    }

    let cancelled = false;
    setArtifactPreview({ loading: true, error: "", text: "", html: "", spreadsheet: null });
    setArtifactDraft("");
    setArtifactSaveFeedback("");
    const previewTarget =
      kind === "spreadsheet"
        ? activeArtifact.preview_json_url || `${activeArtifact.preview_url}${activeArtifact.preview_url.includes("?") ? "&" : "?"}format=json`
        : activeArtifact.preview_url;
    fetch(previewTarget)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`预览加载失败: HTTP ${response.status}`);
        }
        return kind === "spreadsheet" ? response.json() : response.text();
      })
      .then((payload) => {
        if (cancelled) return;
        if (kind === "spreadsheet") {
          setArtifactPreview({ loading: false, error: "", text: "", html: "", spreadsheet: payload });
          return;
        }
        const text = payload;
        if (kind === "markdown") {
          const rawHtml = marked.parse(text, { gfm: true, breaks: true });
          setArtifactPreview({
            loading: false,
            error: "",
            text,
            html: DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } }),
            spreadsheet: null,
          });
          setArtifactDraft(text);
          return;
        }
        setArtifactPreview({ loading: false, error: "", text, html: "", spreadsheet: null });
        setArtifactDraft(text);
      })
      .catch((loadError) => {
        if (cancelled) return;
        setArtifactPreview({ loading: false, error: loadError.message, text: "", html: "", spreadsheet: null });
      });
    return () => {
      cancelled = true;
    };
  }, [uiState.showArtifactModal, activeArtifactPreviewKey]);

  useEffect(() => {
    void loadMeta();
    void loadHistory();
  }, []);

  async function loadMeta() {
    try {
      const response = await fetch("/api/demo/meta");
      const payload = await parseApiResponse(response);
      if (!response.ok) return;
      setModelName(payload.model || "");
      setDemoState((current) => ({
        ...current,
        agents: (payload.agents || []).map((agent) => {
          const existing = current.agents.find((item) => item.id === agent.id);
          return normalizeAgent(agent, existing);
        }),
      }));
    } catch {
      return;
    }
  }

  async function loadHistory() {
    try {
      const cachedThreadId = window.localStorage.getItem(LAST_THREAD_STORAGE_KEY) || threadId;
      const cachedSessions = readCachedThreadHistory(cachedThreadId);
      const endpoint = cachedThreadId ? `/api/demo/history?thread_id=${encodeURIComponent(cachedThreadId)}` : "/api/demo/history";
      const response = await fetch(endpoint);
      const payload = await parseApiResponse(response);
      if (!response.ok) return;
      const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      const normalizedSessions = sessions.map((session) => ({
        id: session.id,
        query: session.query || "",
        state: mergeSessionState(cloneBaseState(), session.state),
        error: session.error || "",
      }));
      const mergedSessions =
        normalizedSessions.length || !cachedSessions.length
          ? normalizedSessions.map((session) => {
              const cached = cachedSessions.find((item) => item.id === session.id);
              const merged = cached ? { ...session, state: mergeSessionState(cached.state, session.state) } : session;
              return hydrateSessionUserFiles(payload.thread_id || cachedThreadId, merged);
            })
          : cachedSessions.map((session) => hydrateSessionUserFiles(cachedThreadId, session));
      if (payload.thread_id) {
        setThreadId(payload.thread_id);
      }
      setUiState((current) =>
        normalizeUiState({
          ...current,
          ...(payload.ui_state || {}),
          showPromptModal: false,
          showHistoryModal: false,
          showArtifactModal: false,
        })
      );
      setPendingUserFiles([]);
      if (mergedSessions.length) {
        setHistory(mergedSessions);
        const lastSession = mergedSessions[mergedSessions.length - 1];
        setDemoState(normalizeSessionState(lastSession.state));
        setError(lastSession.error || "");
      }
    } catch {
      return;
    }
  }

  async function loadHistoryThreads() {
    setHistoryThreadsLoading(true);
    setHistoryThreadsError("");
    try {
      const response = await fetch("/api/demo/history/threads");
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "history_threads_failed");
      setHistoryThreads(Array.isArray(payload.threads) ? payload.threads : []);
    } catch (loadError) {
      setHistoryThreadsError(`加载历史线程失败: ${loadError.message}`);
    } finally {
      setHistoryThreadsLoading(false);
    }
  }

  async function loadPrompts() {
    setPromptLoading(true);
    setPromptError("");
    try {
      const response = await fetch("/api/demo/prompts");
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "prompt_load_failed");
      const prompts = Array.isArray(payload.prompts) ? payload.prompts : [];
      setPromptSections(prompts);
      setUiState((current) => {
        const nextId = current.activePromptId || prompts[0]?.id || "";
        const matched = prompts.find((item) => item.id === nextId) || prompts[0];
        return normalizeUiState({
          ...current,
          activePromptId: nextId,
          promptDraft: matched?.content || "",
        });
      });
    } catch (loadError) {
      setPromptError(`加载提示词失败: ${loadError.message}`);
    } finally {
      setPromptLoading(false);
    }
  }

  function openPromptCenter() {
    setUiState((current) => normalizeUiState({ ...current, showPromptModal: true }));
    setPromptSaveFeedback("");
    setPromptSaveFeedbackTone("");
    if (!promptSections.length && !promptLoading) {
      void loadPrompts();
    }
  }

  function openHistoryCenter() {
    setUiState((current) => normalizeUiState({ ...current, showHistoryModal: true }));
    if (!historyThreads.length && !historyThreadsLoading) {
      void loadHistoryThreads();
    }
  }

  useEffect(() => {
    if (promptSaveFeedbackTone !== "success" || !promptSaveFeedback) return undefined;
    const timer = window.setTimeout(() => {
      setPromptSaveFeedback("");
      setPromptSaveFeedbackTone("");
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [promptSaveFeedback, promptSaveFeedbackTone]);

  useEffect(() => {
    if (!promptSections.length) return;
    const activePrompt = promptSections.find((item) => item.id === uiState.activePromptId) || promptSections[0] || null;
    if (!activePrompt) return;
    setUiState((current) => {
      const nextId = activePrompt.id;
      const draftShouldUpdate =
        current.activePromptId !== nextId || !current.promptDraft || current.promptDraft === "";
      if (current.activePromptId === nextId && !draftShouldUpdate) {
        return current;
      }
      return normalizeUiState({
        ...current,
        activePromptId: nextId,
        promptDraft: draftShouldUpdate ? activePrompt.content || "" : current.promptDraft,
      });
    });
  }, [promptSections, uiState.activePromptId]);

  useEffect(() => {
    if (!threadId) return undefined;
    const snapshot = buildUiStateSnapshot(uiState);
    if (uiStateSaveTimerRef.current) {
      window.clearTimeout(uiStateSaveTimerRef.current);
    }
    uiStateSaveTimerRef.current = window.setTimeout(() => {
      void fetch("/api/demo/thread-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          ui_state: snapshot,
        }),
      }).catch(() => {});
    }, 250);
    return () => {
      if (uiStateSaveTimerRef.current) {
        window.clearTimeout(uiStateSaveTimerRef.current);
      }
    };
  }, [threadId, uiState]);

  async function handleSavePrompt() {
    const activePrompt = promptSections.find((item) => item.id === uiState.activePromptId);
    if (!activePrompt || promptSaving || promptResetting) return;

    setPromptSaving(true);
    setPromptSaveFeedback("");
    setPromptSaveFeedbackTone("");
    try {
      const response = await fetch("/api/demo/prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: activePrompt.id,
          content: uiState.promptDraft,
        }),
      });
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "prompt_update_failed");
      const prompts = Array.isArray(payload.prompts) ? payload.prompts : [];
      setPromptSections(prompts);
      const matched = prompts.find((item) => item.id === activePrompt.id) || payload.prompt;
      setUiState((current) => normalizeUiState({ ...current, promptDraft: matched?.content || current.promptDraft }));
      setPromptSaveFeedback("保存成功，后续运行会使用新的提示词。");
      setPromptSaveFeedbackTone("success");
    } catch (saveError) {
      setPromptSaveFeedback(`保存失败: ${saveError.message}`);
      setPromptSaveFeedbackTone("error");
    } finally {
      setPromptSaving(false);
    }
  }

  async function handleResetPrompt() {
    const activePrompt = promptSections.find((item) => item.id === uiState.activePromptId);
    if (!activePrompt || promptSaving || promptResetting) return;

    setPromptResetting(true);
    setPromptSaveFeedback("");
    setPromptSaveFeedbackTone("");
    try {
      const response = await fetch("/api/demo/prompts/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: activePrompt.id }),
      });
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "prompt_reset_failed");
      const prompts = Array.isArray(payload.prompts) ? payload.prompts : [];
      setPromptSections(prompts);
      const matched = prompts.find((item) => item.id === activePrompt.id) || payload.prompt;
      setUiState((current) => normalizeUiState({ ...current, promptDraft: matched?.content || "" }));
      setPromptSaveFeedback("已恢复默认提示词。");
      setPromptSaveFeedbackTone("success");
    } catch (resetError) {
      setPromptSaveFeedback(`恢复失败: ${resetError.message}`);
      setPromptSaveFeedbackTone("error");
    } finally {
      setPromptResetting(false);
    }
  }

  async function handleSelectThread(nextThreadId) {
    if (!nextThreadId || nextThreadId === threadId) {
      setUiState((current) => normalizeUiState({ ...current, showHistoryModal: false }));
      return;
    }
    await clearPendingUserFiles();
    try {
      const response = await fetch(`/api/demo/history?thread_id=${encodeURIComponent(nextThreadId)}`);
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "history_load_failed");
      const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      const normalizedSessions = sessions.map((session) => ({
        id: session.id,
        query: session.query || "",
        state: mergeSessionState(cloneBaseState(), session.state),
        error: session.error || "",
      }));
      setThreadId(payload.thread_id || nextThreadId);
      setUiState((current) =>
        normalizeUiState({
          ...current,
          ...(payload.ui_state || {}),
          showHistoryModal: false,
        })
      );
      setPendingUserFiles([]);
      const mergedSessions = normalizedSessions.map((session) => {
        const cached = readCachedThreadHistory(payload.thread_id || nextThreadId).find((item) => item.id === session.id);
        const merged = cached ? { ...session, state: mergeSessionState(cached.state, session.state) } : session;
        return hydrateSessionUserFiles(payload.thread_id || nextThreadId, merged);
      });
      setHistory(mergedSessions);
      if (mergedSessions.length) {
        const lastSession = mergedSessions[mergedSessions.length - 1];
        setDemoState(normalizeSessionState(lastSession.state));
        setError(lastSession.error || "");
      } else {
        setDemoState(cloneBaseState());
        setError("");
      }
    } catch (loadError) {
      setHistoryThreadsError(`切换历史线程失败: ${loadError.message}`);
    }
  }

  async function handleDeleteThread(targetThreadId) {
    if (!targetThreadId || deletingThreadId) return;
    setDeletingThreadId(targetThreadId);
    setHistoryThreadsError("");
    try {
      const response = await fetch(`/api/demo/history?thread_id=${encodeURIComponent(targetThreadId)}`, {
        method: "DELETE",
      });
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "history_delete_failed");

      const remainingThreads = historyThreads.filter((thread) => thread.thread_id !== targetThreadId);
      setHistoryThreads(remainingThreads);
      removeCachedSessionUserFilesForThread(targetThreadId);

      if (threadId !== targetThreadId) {
        return;
      }

      if (payload.latest_thread_id) {
        await handleSelectThread(payload.latest_thread_id);
        return;
      }

      setThreadId(createThreadId());
      setHistory([]);
      window.localStorage.removeItem(historyCacheKey(threadId));
      setError("");
      setDemoState((current) => ({
        ...cloneBaseState(),
        agents: current.agents,
      }));
      setUiState((current) =>
        normalizeUiState({
          ...DEFAULT_UI_STATE,
          theme: current.theme,
          activePromptId: current.activePromptId,
          promptDraft: current.promptDraft,
          showHistoryModal: false,
        })
      );
    } catch (deleteError) {
      setHistoryThreadsError(`删除历史线程失败: ${deleteError.message}`);
    } finally {
      setDeletingThreadId("");
      setDeleteConfirm(EMPTY_DELETE_CONFIRM);
    }
  }

  function handleChooseUserFile() {
    if (loading) return;
    fileInputRef.current?.click();
  }

  function updatePendingUserFile(targetId, updater) {
    setPendingUserFiles((current) =>
      current.map((item) => (item.id === targetId ? { ...item, ...(typeof updater === "function" ? updater(item) : updater) } : item))
    );
  }

  function uploadPendingUserFile(pendingFile) {
    const request = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("thread_id", threadId);
    formData.append("user_file", pendingFile.file, pendingFile.name);
    request.open("POST", "/api/demo/user-file");
    request.responseType = "text";
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const progress = Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100)));
      updatePendingUserFile(pendingFile.id, { progress, status: "uploading" });
    };
    request.onerror = () => {
      uploadControllersRef.current.delete(pendingFile.id);
      updatePendingUserFile(pendingFile.id, { status: "error", progress: 0, error: "上传失败。" });
    };
    request.onabort = () => {
      uploadControllersRef.current.delete(pendingFile.id);
    };
    request.onload = () => {
      uploadControllersRef.current.delete(pendingFile.id);
      try {
        const payload = request.responseText ? JSON.parse(request.responseText) : {};
        if (request.status < 200 || request.status >= 300) {
          throw new Error(payload.error || "upload_failed");
        }
        const file = payload.file || {};
        updatePendingUserFile(pendingFile.id, {
          path: file.path || "",
          preview_url: file.preview_url || "",
          preview_json_url: file.preview_json_url || "",
          download_url: file.download_url || "",
          updated_at: file.updated_at || new Date().toISOString(),
          mime_type: file.mime_type || pendingFile.mime_type,
          extension: file.extension || pendingFile.extension,
          size: file.size ?? pendingFile.size,
          title: pendingFile.name,
          original_name: pendingFile.name,
          progress: 100,
          status: "ready",
          error: "",
          file: pendingFile.file,
        });
      } catch (uploadError) {
        updatePendingUserFile(pendingFile.id, {
          status: "error",
          progress: 0,
          error: uploadError.message || "上传失败。",
        });
      }
    };
    uploadControllersRef.current.set(pendingFile.id, request);
    request.send(formData);
  }

  function handlePendingFileChange(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    if (pendingUserFiles.length + files.length > MAX_USER_FILE_COUNT) {
      setUploadError(`最多上传 ${MAX_USER_FILE_COUNT} 个文件。`);
      return;
    }

    const nextFiles = [];
    for (const file of files) {
      const validationError = validatePendingUserFile(file);
      if (validationError) {
        setUploadError(validationError);
        return;
      }
      nextFiles.push({ ...createPendingUserFile(file), status: "uploading", progress: 0, error: "" });
    }
    setUploadError("");
    setPendingUserFiles((current) => [...current, ...nextFiles].slice(0, MAX_USER_FILE_COUNT));
    for (const pendingFile of nextFiles) {
      uploadPendingUserFile(pendingFile);
    }
  }

  async function handleRemovePendingUserFile(targetId) {
    const target = pendingUserFiles.find((item) => item.id === targetId);
    const inflight = uploadControllersRef.current.get(targetId);
    if (inflight) {
      inflight.abort();
      uploadControllersRef.current.delete(targetId);
    }
    if (target?.path) {
      try {
        await fetch(`/api/demo/user-file?path=${encodeURIComponent(target.path)}`, { method: "DELETE" });
      } catch {}
    }
    setPendingUserFiles((current) => current.filter((item) => item.id !== targetId));
    setUploadError("");
  }

  async function clearPendingUserFiles() {
    const currentFiles = [...pendingUserFiles];
    for (const item of currentFiles) {
      const inflight = uploadControllersRef.current.get(item.id);
      if (inflight) {
        inflight.abort();
        uploadControllersRef.current.delete(item.id);
      }
      if (item.path) {
        try {
          await fetch(`/api/demo/user-file?path=${encodeURIComponent(item.path)}`, { method: "DELETE" });
        } catch {}
      }
    }
    setPendingUserFiles([]);
    setUploadError("");
    setUploadProgress(0);
  }

  async function handleRun() {
    const trimmed = uiState.query.trim();
    if (loading) return;
    if (!trimmed) {
      if (pendingUserFiles.length) {
        setUploadError("仅上传文件不能发送，请先输入问题。");
      }
      return;
    }
    if (pendingUserFiles.length > MAX_USER_FILE_COUNT) {
      setUploadError(`最多上传 ${MAX_USER_FILE_COUNT} 个文件。`);
      return;
    }
    for (const pendingFile of pendingUserFiles) {
      if (pendingFile.file) {
        const validationError = validatePendingUserFile(pendingFile.file);
        if (validationError) {
          setUploadError(validationError);
          return;
        }
      } else if (!pendingFile.path) {
        setUploadError("存在未完成上传的文件，请移除后重试。");
        return;
      }
      if (pendingFile.status === "uploading") {
        setUploadError("仍有文件上传中，请等待完成后再发送。");
        return;
      }
      if (pendingFile.status === "error") {
        setUploadError("存在上传失败的文件，请移除后重试。");
        return;
      }
    }

    const sessionId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const messageHistory = history.flatMap((session) => {
      const items = [{ role: "user", content: session.query }];
      if (session.state.final_summary) {
        items.push({ role: "assistant", content: session.state.final_summary });
      }
      return items;
    });
    const localUserFiles = pendingUserFiles.filter((item) => item.path).map((item) => ({
      ...item,
      original_name: item.original_name || item.name,
    }));
    setLoading(true);
    setError("");
    setUploadError("");
    setUploadProgress(0);
    const nextState = {
      ...cloneBaseState(),
      agents: demoState.agents,
      query: trimmed,
      user_files: localUserFiles,
      status: "running",
      scheduler_thought: "Supervisor 正在分析 query，准备建立本轮 Action List。",
    };
    const nextSessionRecord = {
      id: sessionId,
      query: trimmed,
      state: nextState,
      error: "",
    };
    const nextHistory = [...history, nextSessionRecord];
    setDemoState(nextState);
    setHistory(nextHistory);
    writeCachedThreadHistory(threadId, nextHistory);
    writeCachedSessionUserFiles(threadId, sessionId, localUserFiles);
    setUiState((current) => normalizeUiState({ ...current, query: DEFAULT_QUERY }));
    setPendingUserFiles([]);

    try {
      const draftPayload = {
        ...nextState,
        user_files: (nextState.user_files || []).map((item) => ({
          id: item.id,
          path: item.path,
          name: item.name,
          title: item.title,
          extension: item.extension,
          size: item.size,
          updated_at: item.updated_at,
          mime_type: item.mime_type,
          preview_url: item.preview_url,
          preview_json_url: item.preview_json_url,
          download_url: item.download_url,
          original_name: item.original_name || item.name,
          source: "user_upload",
        })),
      };
      await fetch("/api/demo/session-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          session_id: sessionId,
          query: trimmed,
          payload: draftPayload,
        }),
      }).catch(() => {});

      const controller = new AbortController();
      runControllerRef.current = controller;
        const response = await fetch("/api/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          query: trimmed,
          thread_id: threadId,
          session_id: sessionId,
          max_rounds: MAX_ROUNDS,
          user_files: localUserFiles.map((item) => ({
            path: item.path,
            name: item.name,
            original_name: item.original_name || item.name,
          })),
          messages: [...messageHistory, { role: "user", content: trimmed }],
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "backend_error");
      }

      const contentType = response.headers.get("content-type") || "";
      if (!response.body || !contentType.includes("application/x-ndjson")) {
        const payload = await response.json();
        const nextPayload = mergeSessionState(nextState, payload);
        setDemoState(nextPayload);
        setHistory((current) =>
          current.map((item) => (item.id === sessionId ? { ...item, state: mergeSessionState(item.state, nextPayload) } : item))
        );
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine) continue;
            const event = JSON.parse(trimmedLine);
            if (!event?.payload) continue;
            const nextPayload = mergeSessionState(nextState, event.payload);
            setDemoState(nextPayload);
            setHistory((current) =>
              current.map((item) =>
                item.id === sessionId
                  ? {
                      ...item,
                      state: mergeSessionState(item.state, nextPayload),
                      error: event.type === "error" ? nextPayload.stop_reason || "执行失败。" : "",
                    }
                  : item
              )
            );
            if (event.type === "error") {
              setError(nextPayload.stop_reason || "执行失败。");
            }
          }
        }

        if (buffer.trim()) {
          const event = JSON.parse(buffer.trim());
          if (event?.payload) {
            const nextPayload = mergeSessionState(nextState, event.payload);
            setDemoState(nextPayload);
            setHistory((current) =>
              current.map((item) =>
                item.id === sessionId
                  ? {
                      ...item,
                      state: mergeSessionState(item.state, nextPayload),
                      error: event.type === "error" ? nextPayload.stop_reason || "执行失败。" : "",
                    }
                  : item
              )
            );
          }
        }
      }
    } catch (runError) {
      if (runError?.name === "AbortError") {
        const stoppedState = {
          ...nextState,
          status: "stopped",
          stop_reason: "Supervisor 已手动停止。",
          scheduler_thought: nextState.scheduler_thought || "执行已被手动中止。",
        };
        setDemoState(stoppedState);
        setHistory((current) =>
          current.map((item) => (item.id === sessionId ? { ...item, state: stoppedState } : item))
        );
        return;
      }
      const message =
        runError?.message === "query_required"
          ? "请输入问题后再发送。"
          : runError?.message === "network_error"
            ? "后端接口不可用，请先运行 `python3 serve_demo.py`。"
            : runError?.message || "后端接口不可用，请先运行 `python3 serve_demo.py`。";
      setError(message);
      const failedState = {
        ...cloneBaseState(),
        agents: demoState.agents,
        query: trimmed,
        user_files: localUserFiles,
        status: "stopped",
        scheduler_thought: "未能拿到后端调度结果。",
        final_summary: "当前没有执行结果返回。",
      };
      setDemoState(failedState);
      setHistory((current) =>
        current.map((item) =>
          item.id === sessionId ? { ...item, state: failedState, error: message } : item
        )
      );
      console.error(runError);
    } finally {
      runControllerRef.current = null;
      setLoading(false);
    }
  }

  function handleStop() {
    runControllerRef.current?.abort();
  }

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    void handleRun();
  }

  function handleNewThread() {
    if (loading) {
      runControllerRef.current?.abort();
      runControllerRef.current = null;
    }
    void clearPendingUserFiles();
    setLoading(false);
    setError("");
    setHistory([]);
    setThreadId(createThreadId());
    setUiState((current) =>
      normalizeUiState({
        ...DEFAULT_UI_STATE,
        theme: current.theme,
        activePromptId: current.activePromptId,
        promptDraft: current.promptDraft,
      })
    );
    setPendingUserFiles([]);
    setDemoState((current) => ({
      ...cloneBaseState(),
      agents: current.agents,
    }));
    void loadMeta();
  }

  function handleOpenArtifact(file) {
    artifactSelectionRef.current = {
      path: file?.path || "",
      originalName: file?.original_name || file?.name || "",
      name: file?.name || "",
    };
    setUiState((current) =>
      normalizeUiState({
        ...current,
        activeArtifactPath: file?.path || "",
        showArtifactModal: Boolean(file?.path),
      })
    );
  }

  async function handleSaveArtifact() {
    if (!activeArtifact || artifactSaving) return;
    setArtifactSaving(true);
    setArtifactSaveFeedback("");
    try {
      const response = await fetch("/api/demo/workspace-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: activeArtifact.path,
          content: artifactDraft,
        }),
      });
      const payload = await parseApiResponse(response);
      if (!response.ok) throw new Error(payload.error || "workspace_file_save_failed");
      const nextFile = payload.file || activeArtifact;
      setDemoState((current) => ({
        ...current,
        files: (current.files || []).map((item) => (item.path === nextFile.path ? { ...item, ...nextFile } : item)),
      }));
      setHistory((current) =>
        current.map((session) => ({
          ...session,
          state: {
            ...session.state,
            files: (session.state.files || []).map((item) => (item.path === nextFile.path ? { ...item, ...nextFile } : item)),
          },
        }))
      );
      const kind = classifyArtifact(nextFile);
      if (kind === "markdown") {
        const rawHtml = marked.parse(artifactDraft, { gfm: true, breaks: true });
        setArtifactPreview({
          loading: false,
          error: "",
          text: artifactDraft,
          html: DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } }),
        });
      } else if (kind === "text") {
        setArtifactPreview({ loading: false, error: "", text: artifactDraft, html: "" });
      }
      setArtifactSaveFeedback("文件已保存。");
    } catch (saveError) {
      setArtifactSaveFeedback(`保存失败: ${saveError.message}`);
    } finally {
      setArtifactSaving(false);
    }
  }

  const completedCount = demoState.tasks.filter((task) => stepState(task.status) === "success").length;
  const runningCount = demoState.tasks.filter((task) => stepState(task.status) === "running").length;
  const workerCount = demoState.agents.filter((agent) => isActiveWorkerStatus(agent.status)).length;

  const headerStatus = useMemo(() => {
    if (error || demoState.status === "stopped") return { label: "错误", icon: ShieldAlert, tone: "error" };
    if (demoState.status === "running") return { label: "进行中", icon: LoaderCircle, tone: "running" };
    if (demoState.status === "done") return { label: "已完成", icon: CheckCircle2, tone: "success" };
    return { label: "待命", icon: Circle, tone: "pending" };
  }, [demoState.status, error]);
  const isEditableArtifact = Boolean(activeArtifact) &&
    ["markdown", "text"].includes(classifyArtifact(activeArtifact)) &&
    activeArtifact.source !== "user_upload";

  return html`<div className="app-shell">
    <aside className="side-rail">
      <div className="side-rail-card">
        <button
          type="button"
          className=${`side-menu-button ${uiState.showHistoryModal ? "is-active" : ""}`}
          onClick=${openHistoryCenter}
          title="查看历史会话"
        >
          <${Clock3} className="h-4 w-4" />
          <span>历史</span>
        </button>
        <button
          type="button"
          className=${`side-menu-button ${uiState.showPromptModal ? "is-active" : ""}`}
          onClick=${openPromptCenter}
          title="预览管理提示词"
        >
          <${BookText} className="h-4 w-4" />
          <span>提示词</span>
        </button>
      </div>
    </aside>
    <div className="dialog-shell">
      <header className="dialog-header">
        <div>
          <div className="app-badge">
            <${TerminalSquare} className="h-4 w-4" />
            <span>Supervisor Agent Console</span>
          </div>
          <h1 className="dialog-title">多 Agent 执行工作台</h1>
          <p className="dialog-subtitle">
            用于拆解任务、调度 worker、跟踪执行过程，并汇总最终结果。
          </p>
        </div>
        <div className="header-side">
          <div className="header-actions">
            <button type="button" onClick=${handleNewThread} className="secondary-button" disabled=${loading}>
              <${MessageSquare} className="h-4 w-4" />
              <span>新会话</span>
            </button>
          </div>
          <${ThemeSwitcher}
            theme=${uiState.theme}
            setTheme=${(nextTheme) => setUiState((current) => normalizeUiState({ ...current, theme: nextTheme }))}
          />
          <div className="thread-meta">thread_id: ${threadId}</div>
        </div>
      </header>

      <div className="stats-row">
        <${StatCard} label="Current round" value=${`${demoState.current_round} / ${demoState.max_rounds || MAX_ROUNDS}`} icon=${Activity} />
        <${StatCard} label="Action steps" value=${String(demoState.tasks.length)} icon=${ClipboardList} />
        <${StatCard} label="Completed" value=${String(completedCount)} icon=${CheckCircle2} />
        <${StatCard} label="Active workers" value=${String(workerCount || runningCount)} icon=${Bot} />
        <${StatusCard} label="Status" value=${headerStatus.label} icon=${headerStatus.icon} tone=${headerStatus.tone} />
      </div>

      <main className="conversation-scroll">
        ${history.length
          ? history.map(
              (session, index) => html`<${SessionTranscript}
                key=${session.id || index}
                session=${session}
                error=${session.error}
                onOpenAgent=${(agent) =>
                  setUiState((current) => normalizeUiState({ ...current, selectedAgentId: agent?.id || "" }))}
                onOpenFile=${handleOpenArtifact}
              />`
            )
          : html`<div className="empty-thread">发送一条消息后，这里会按轮次保留完整问答记录。</div>`}
      </main>

      <div className="composer-dock">
        <div className="composer-stack">
          ${loading
            ? html`<div className="composer-shell is-collapsed">
                <div className="composer-collapsed-note">
                  <${LoaderCircle} className="h-4 w-4 animate-spin" />
                  <span>Supervisor 正在执行，对话框已收起</span>
                </div>
                <div className="composer-actions composer-actions-minimal">
                  <button
                    type="button"
                    onClick=${handleStop}
                    className="primary-button send-button stop-button"
                    aria-label="停止执行"
                  >
                    <${Square} className="h-4 w-4" />
                  </button>
                </div>
              </div>`
            : html`${pendingUserFiles.length
                ? html`<div className="composer-pending-overlay">
                    <div className="pending-upload-panel">
                      <div className="pending-upload-header">
                        <span>待上传文件</span>
                        <span>${pendingUserFiles.length}/${MAX_USER_FILE_COUNT}</span>
                      </div>
                      <div className="pending-upload-grid">
                        ${pendingUserFiles.map(
                          (pendingFile) => html`<div key=${pendingFile.id} className="pending-upload-card is-compact">
                            <div className="pending-upload-main">
                              <div className="artifact-icon-wrap">
                                <${iconForArtifact(pendingFile)} className="h-4 w-4" />
                              </div>
                              <div className="pending-upload-copy">
                                <div className="pending-upload-title">${pendingFile.name}</div>
                                <div className="pending-upload-meta">${formatFileSize(pendingFile.size)} · ${pendingFile.extension}</div>
                              </div>
                              <button
                                type="button"
                                className="icon-button"
                                onClick=${() => handleRemovePendingUserFile(pendingFile.id)}
                                aria-label="移除文件"
                              >
                                <${Trash2} className="h-4 w-4" />
                              </button>
                            </div>
                            <div className=${`upload-progress-track ${pendingUploadTone(pendingFile.status)}`}>
                              <span className="upload-progress-fill" style=${{ width: `${pendingFile.progress || 0}%` }}></span>
                            </div>
                            <div className="pending-upload-foot">
                              <div className="pending-upload-meta">
                                ${
                                  pendingFile.status === "uploading"
                                    ? "上传中"
                                    : pendingFile.status === "error"
                                      ? pendingFile.error || "上传失败"
                                      : "已上传，待发送"
                                }
                              </div>
                              ${
                                pendingFile.status === "error"
                                  ? null
                                  : html`<div className="pending-upload-percent">${Math.max(0, Math.min(100, pendingFile.progress || 0))}%</div>`
                              }
                            </div>
                          </div>`
                        )}
                      </div>
                    </div>
                  </div>`
                : null}
                <div className="composer-model-bubble">Model: ${modelName || "unknown"}</div>
                <div className="composer-shell">
                  <input
                    ref=${fileInputRef}
                    type="file"
                    className="hidden-file-input"
                    multiple=${true}
                    accept=${ALLOWED_USER_FILE_EXTENSIONS.join(",")}
                    onChange=${handlePendingFileChange}
                  />
                  <div className="composer-leading">
                    <button
                      type="button"
                      onClick=${handleChooseUserFile}
                      className="ghost-button upload-button"
                      aria-label="添加文件"
                      disabled=${loading}
                    >
                      <${Plus} className="h-4 w-4" />
                    </button>
                  </div>
                  <label className="composer-input-wrap" aria-label="User Query">
                    <span className="composer-label">User Query</span>
                    <textarea
                      value=${uiState.query}
                      onChange=${(event) => setUiState((current) => normalizeUiState({ ...current, query: event.target.value }))}
                      onKeyDown=${handleComposerKeyDown}
                      className="composer-area"
                      placeholder="给 Supervisor 输入一个需要拆解并调度多 worker 的任务"
                    ></textarea>
                    ${uploadError ? html`<div className="composer-inline-error">${uploadError}</div>` : null}
                  </label>
                  <div className="composer-actions composer-actions-minimal">
                    <button
                      type="button"
                      onClick=${handleRun}
                      className="primary-button send-button"
                      aria-label="发送"
                      disabled=${loading || !uiState.query.trim() || pendingUserFiles.some((item) => item.status === "uploading")}
                    >
                      <${ArrowUp} className="h-4 w-4" />
                    </button>
                  </div>
                </div>`}
        </div>
      </div>
    </div>

    <${Modal}
      open=${uiState.showHistoryModal}
      title="历史会话"
      eyebrow="历史会话"
      onClose=${() => setUiState((current) => normalizeUiState({ ...current, showHistoryModal: false }))}
      variant="prompt-center"
    >
      <${HistoryCenter}
        threads=${historyThreads}
        activeThreadId=${threadId}
        onSelectThread=${handleSelectThread}
        onDeleteThread=${(targetThreadId) => setDeleteConfirm({ open: true, threadId: targetThreadId })}
        deletingThreadId=${deletingThreadId}
        loading=${historyThreadsLoading}
        error=${historyThreadsError}
        interactionLocked=${loading}
      />
    </${Modal}>

    <${Modal}
      open=${deleteConfirm.open}
      title="删除历史线程"
      eyebrow="历史会话"
      onClose=${() => (deletingThreadId ? null : setDeleteConfirm(EMPTY_DELETE_CONFIRM))}
      variant="confirm"
    >
      <div className="stack-block confirm-stack">
        <div className="note-block">
          该操作会删除这条线程下的全部会话历史和线程级 UI 状态，且无法恢复。
        </div>
        <div className="info-card wide">
          <div className="info-label">Thread ID</div>
          <div className="info-value">${deleteConfirm.threadId || "-"}</div>
        </div>
        <div className="prompt-toolbar-actions confirm-actions">
          <button
            type="button"
            className="secondary-button"
            onClick=${() => setDeleteConfirm(EMPTY_DELETE_CONFIRM)}
            disabled=${Boolean(deletingThreadId)}
          >
            取消
          </button>
          <button
            type="button"
            className="primary-button stop-button"
            onClick=${() => handleDeleteThread(deleteConfirm.threadId)}
            disabled=${Boolean(deletingThreadId)}
          >
            ${deletingThreadId ? html`<${LoaderCircle} className="h-4 w-4 animate-spin" />` : html`<${Trash2} className="h-4 w-4" />`}
            <span>${deletingThreadId ? "删除中" : "确认删除"}</span>
          </button>
        </div>
      </div>
    </${Modal}>

    <${Modal}
      open=${uiState.showPromptModal}
      title="管理提示词预览"
      eyebrow="提示词管理"
      onClose=${() => setUiState((current) => normalizeUiState({ ...current, showPromptModal: false }))}
      variant="prompt-center"
    >
      <${PromptCenter}
        prompts=${promptSections}
        activePromptId=${uiState.activePromptId}
        onSelect=${(nextPromptId) =>
          setUiState((current) => {
            const matched = promptSections.find((item) => item.id === nextPromptId) || null;
            return normalizeUiState({
              ...current,
              activePromptId: nextPromptId,
              promptDraft: matched?.content || "",
            });
          })}
        loading=${promptLoading}
        error=${promptError}
        draftContent=${uiState.promptDraft}
        onDraftChange=${(nextDraft) => setUiState((current) => normalizeUiState({ ...current, promptDraft: nextDraft }))}
        onSave=${handleSavePrompt}
        onReset=${handleResetPrompt}
        saveFeedback=${promptSaveFeedback}
        saveFeedbackTone=${promptSaveFeedbackTone}
        saving=${promptSaving}
        resetting=${promptResetting}
        readOnly=${loading}
      />
    </${Modal}>

    <${Modal}
      open=${uiState.showArtifactModal && Boolean(activeArtifact)}
      title=${activeArtifact ? activeArtifact.title || activeArtifact.name : "文件预览"}
      eyebrow="文件预览"
      onClose=${() =>
        setUiState((current) =>
          normalizeUiState({ ...current, showArtifactModal: false, activeArtifactPath: "" }))}
      variant="file-preview"
    >
      ${
        activeArtifact
          ? html`<div className="stack-block file-preview-stack">
              <div className="prompt-meta-card">
                <div>
                  <div className="summary-title">${activeArtifact.original_name || activeArtifact.name || activeArtifact.title}</div>
                  <div className="summary-subtitle">${formatUtc8Timestamp(activeArtifact.updated_at)}</div>
                </div>
                <span className="tag">${activeArtifact.extension || "(无后缀)"}</span>
              </div>
              <div className="prompt-toolbar">
                <span className="prompt-toolbar-note">${formatFileSize(activeArtifact.size)} · ${activeArtifact.mime_type}</span>
                <div className="prompt-toolbar-actions">
                  ${isEditableArtifact
                    ? html`<button type="button" className="secondary-button" onClick=${handleSaveArtifact} disabled=${artifactSaving}>
                        ${artifactSaving ? html`<${LoaderCircle} className="h-4 w-4 animate-spin" />` : null}
                        <span>${artifactSaving ? "保存中" : "保存修改"}</span>
                      </button>`
                    : null}
                  <a href=${activeArtifact.download_url} className="primary-button" download>
                    <span>下载文件</span>
                  </a>
                </div>
              </div>
              ${artifactSaveFeedback ? html`<div className=${artifactSaveFeedback.startsWith("保存失败") ? "alert-block" : "success-block"}>${artifactSaveFeedback}</div>` : null}
              ${
                isEditableArtifact
                  ? html`<div className="artifact-editor-grid">
                      <label className="form-field artifact-editor-pane">
                        <div className="form-label">编辑内容</div>
                        <textarea
                          className="field-control field-area prompt-editor artifact-editor"
                          value=${artifactDraft}
                          onChange=${(event) => setArtifactDraft(event.target.value)}
                          spellCheck="false"
                        ></textarea>
                      </label>
                      <div className="stack-block artifact-preview-pane">
                        <div className="form-label">预览</div>
                        <${FilePreviewContent} file=${activeArtifact} previewState=${artifactPreview.loading ? artifactPreview : { ...artifactPreview, text: artifactDraft, html: classifyArtifact(activeArtifact) === "markdown" ? DOMPurify.sanitize(marked.parse(artifactDraft, { gfm: true, breaks: true }), { USE_PROFILES: { html: true } }) : "" }} />
                      </div>
                    </div>`
                  : html`<${FilePreviewContent} file=${activeArtifact} previewState=${artifactPreview} />`
              }
            </div>`
          : html`<div className="empty-block">未找到文件产物。</div>`
      }
    </${Modal}>

    <${Modal}
      open=${Boolean(selectedAgent)}
      title=${selectedAgent ? `${selectedAgent.name} Metadata` : ""}
      onClose=${() => setUiState((current) => normalizeUiState({ ...current, selectedAgentId: "" }))}
    >
      ${
        selectedAgent
          ? html`<div className="detail-grid modal-grid">
              <${InfoCard} label="ID" value=${selectedAgent.id} />
              <${InfoCard} label="Name" value=${selectedAgent.name} />
              <${InfoCard} label="Role" value=${selectedAgent.role || "未定义"} />
              <${InfoCard} label="Status" value=${stepLabel(selectedAgent.status)} />
              <${InfoCard} label="Current task" value=${selectedAgent.current_task_title || "待命中"} wide=${true} />
              <${InfoCard} label="Description" value=${selectedAgent.description || "未提供"} wide=${true} />
              <${InfoCard} label="Recent report" value=${selectedAgent.report || "本轮尚未汇报"} wide=${true} />
              <${InfoCard} label="Guard" value=${selectedAgent.last_guard_message || "最近没有 guard 拦截"} wide=${true} />
            </div>`
          : null
      }
    </${Modal}>

  </div>`;
}

function StatCard({ icon: Icon, label, value }) {
  return html`<div className="stat-card">
    <div className="stat-label">
      <${Icon} className="h-4 w-4" />
      <span>${label}</span>
    </div>
    <div className="stat-value">${value}</div>
  </div>`;
}

function StatusCard({ icon: Icon, label, value, tone }) {
  return html`<div className=${`stat-card status-card ${tone ? `is-${tone}` : ""}`}>
    <div className="stat-label">
      <${Icon} className=${`h-4 w-4 ${tone === "running" ? "animate-spin" : ""}`} />
      <span>${label}</span>
    </div>
    <div className="stat-value">${value}</div>
  </div>`;
}

function InfoCard({ label, value, wide = false }) {
  return html`<div className=${`info-card ${wide ? "wide" : ""}`}>
    <div className="info-label">${label}</div>
    <div className="info-value">${value}</div>
  </div>`;
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("root_not_found");

createRoot(rootElement).render(html`<${App} />`);
