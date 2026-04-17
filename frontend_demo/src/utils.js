import {
  ALLOWED_USER_FILE_EXTENSIONS,
  DEFAULT_THEME,
  DEFAULT_UI_STATE,
  EMPTY_STATE,
  HISTORY_CACHE_PREFIX,
  LAST_THREAD_STORAGE_KEY,
  MAX_USER_FILE_SIZE,
  SESSION_USER_FILES_CACHE_PREFIX,
  THEMES,
} from "./constants.js";

export function createThreadId() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return `thread_${stamp}_${suffix}`;
}

export function fileExtension(name = "") {
  const match = String(name).toLowerCase().match(/(\.[^.]+)$/);
  return match ? match[1] : "";
}

export function normalizeUiState(snapshot = {}) {
  const nextTheme = typeof snapshot.theme === "string" ? snapshot.theme : DEFAULT_UI_STATE.theme;
  const normalizedTheme = THEMES.some((item) => item.id === nextTheme) ? nextTheme : DEFAULT_THEME;
  return {
    theme: normalizedTheme,
    query: typeof snapshot.query === "string" ? snapshot.query : DEFAULT_UI_STATE.query,
    showPromptModal:
      typeof snapshot.showPromptModal === "boolean"
        ? snapshot.showPromptModal
        : typeof snapshot.show_prompt_modal === "boolean"
          ? snapshot.show_prompt_modal
          : DEFAULT_UI_STATE.showPromptModal,
    showSkillModal:
      typeof snapshot.showSkillModal === "boolean"
        ? snapshot.showSkillModal
        : typeof snapshot.show_skill_modal === "boolean"
          ? snapshot.show_skill_modal
          : DEFAULT_UI_STATE.showSkillModal,
    showHistoryModal:
      typeof snapshot.showHistoryModal === "boolean"
        ? snapshot.showHistoryModal
        : typeof snapshot.show_history_modal === "boolean"
          ? snapshot.show_history_modal
          : DEFAULT_UI_STATE.showHistoryModal,
    showToolModal:
      typeof snapshot.showToolModal === "boolean"
        ? snapshot.showToolModal
        : typeof snapshot.show_tool_modal === "boolean"
          ? snapshot.show_tool_modal
          : DEFAULT_UI_STATE.showToolModal,
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
    activeSkillId:
      typeof snapshot.activeSkillId === "string"
        ? snapshot.activeSkillId
        : typeof snapshot.active_skill_id === "string"
          ? snapshot.active_skill_id
          : DEFAULT_UI_STATE.activeSkillId,
    activeToolId:
      typeof snapshot.activeToolId === "string"
        ? snapshot.activeToolId
        : typeof snapshot.active_tool_id === "string"
          ? snapshot.active_tool_id
          : DEFAULT_UI_STATE.activeToolId,
    promptDraft:
      typeof snapshot.promptDraft === "string"
        ? snapshot.promptDraft
        : typeof snapshot.prompt_draft === "string"
          ? snapshot.prompt_draft
          : DEFAULT_UI_STATE.promptDraft,
    skillDraft:
      typeof snapshot.skillDraft === "string"
        ? snapshot.skillDraft
        : typeof snapshot.skill_draft === "string"
          ? snapshot.skill_draft
          : DEFAULT_UI_STATE.skillDraft,
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

export function buildUiStateSnapshot(uiState) {
  const normalized = normalizeUiState(uiState);
  return {
    theme: normalized.theme,
    query: normalized.query,
    showPromptModal: false,
    showSkillModal: false,
    showHistoryModal: false,
    showToolModal: false,
    showArtifactModal: false,
    activePromptId: normalized.activePromptId,
    activeSkillId: normalized.activeSkillId,
    activeToolId: normalized.activeToolId,
    promptDraft: normalized.promptDraft,
    skillDraft: normalized.skillDraft,
    selectedAgentId: normalized.selectedAgentId,
    activeArtifactPath: normalized.activeArtifactPath,
  };
}

export function cloneBaseState() {
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

export function normalizeAgent(agent, existing = {}) {
  const role = agent.role || existing.role || "";
  const description = agent.description || existing.description || "";
  const scope = agent.scope || existing.scope || role || description || "";
  return {
    id: agent.id,
    name: agent.name || existing.name || agent.id,
    scope,
    role,
    description,
    status: agent.status || existing.status || "idle",
    current_task_title: agent.current_task_title || existing.current_task_title || "",
    report: agent.report || existing.report || "",
    todo_list: agent.todo_list || existing.todo_list || [],
    completed_rounds: agent.completed_rounds ?? existing.completed_rounds ?? 0,
    guard_hits: agent.guard_hits ?? existing.guard_hits ?? 0,
    last_guard_message: agent.last_guard_message || existing.last_guard_message || "",
  };
}

export function normalizeSessionState(snapshot = {}) {
  return {
    ...cloneBaseState(),
    ...(snapshot || {}),
    tasks: Array.isArray(snapshot?.tasks) ? snapshot.tasks : [],
    rounds: Array.isArray(snapshot?.rounds) ? snapshot.rounds : [],
    agents: Array.isArray(snapshot?.agents) ? snapshot.agents.map((agent) => normalizeAgent(agent)) : [],
    files: Array.isArray(snapshot?.files) ? snapshot.files : [],
    user_files: Array.isArray(snapshot?.user_files) ? snapshot.user_files : [],
    logs: Array.isArray(snapshot?.logs) ? snapshot.logs : [],
  };
}

export function mergeSessionState(existingState, nextState) {
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

export function historyCacheKey(threadId) {
  return `${HISTORY_CACHE_PREFIX}${threadId}`;
}

export function sessionUserFilesCacheKey(threadId, sessionId) {
  return `${SESSION_USER_FILES_CACHE_PREFIX}${threadId}:${sessionId}`;
}

export function sanitizeUserFiles(files = []) {
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

export function readCachedSessionUserFiles(threadId, sessionId) {
  if (!threadId || !sessionId) return [];
  try {
    const raw = window.localStorage.getItem(sessionUserFilesCacheKey(threadId, sessionId));
    if (!raw) return [];
    return sanitizeUserFiles(JSON.parse(raw));
  } catch {
    return [];
  }
}

export function writeCachedSessionUserFiles(threadId, sessionId, userFiles) {
  if (!threadId || !sessionId) return;
  try {
    const sanitized = sanitizeUserFiles(userFiles);
    if (!sanitized.length) return;
    window.localStorage.setItem(sessionUserFilesCacheKey(threadId, sessionId), JSON.stringify(sanitized));
  } catch {
    return;
  }
}

export function removeCachedSessionUserFilesForThread(threadId) {
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

export function hydrateSessionUserFiles(threadId, session) {
  const localUserFiles = readCachedSessionUserFiles(threadId, session.id);
  if (!localUserFiles.length) return session;
  return {
    ...session,
    state: mergeSessionState({ ...session.state, user_files: localUserFiles }, session.state),
  };
}

export function sanitizeHistorySessions(sessions = []) {
  return sessions.map((session) => ({
    id: session.id,
    query: session.query || "",
    state: normalizeSessionState(session.state),
    error: session.error || "",
  }));
}

export function readCachedThreadHistory(threadId) {
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

export function writeCachedThreadHistory(threadId, sessions) {
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

export function validatePendingUserFile(file) {
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

export function createPendingUserFile(file) {
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

export function pendingUploadTone(status) {
  if (status === "error") return "is-error";
  if (status === "ready") return "is-ready";
  return "is-uploading";
}

export function formatUtc8Timestamp(value) {
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

export function formatFileSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function classifyArtifact(file) {
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

export function stepState(status) {
  if (status === "blocked") return "blocked";
  if (status === "running" || status === "in_progress") return "running";
  if (status === "done" || status === "completed" || status === "success") return "success";
  if (status === "error" || status === "failed") return "error";
  return "pending";
}

export function stepLabel(status) {
  if (status === "blocked") return "已阻塞";
  const value = stepState(status);
  if (value === "running") return "进行中";
  if (value === "success") return "已完成";
  if (value === "error") return "错误";
  return "待处理";
}

export function statusClass(status) {
  const value = stepState(status);
  if (value === "blocked") return "is-blocked";
  if (value === "running") return "is-running";
  if (value === "success") return "is-success";
  if (value === "error") return "is-error";
  return "is-pending";
}

export function isActiveWorkerStatus(status) {
  return ["pending", "running", "in_progress", "blocked"].includes(status);
}

export function stringifyYamlScalar(value) {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (value == null) return '""';
  const text = String(value);
  if (!text.length) return '""';
  if (/^[\w./:-]+$/u.test(text) && !/^(true|false|null|~)$/i.test(text)) {
    return text;
  }
  return JSON.stringify(text);
}

export function buildRawSkillDocument(frontmatter = {}, body = "") {
  const entries = Object.entries(frontmatter || {});
  const lines = ["---"];
  for (const [key, value] of entries) {
    if (Array.isArray(value)) {
      lines.push(`${key}:`);
      for (const item of value) {
        lines.push(`  - ${stringifyYamlScalar(item)}`);
      }
      continue;
    }
    lines.push(`${key}: ${stringifyYamlScalar(value)}`);
  }
  lines.push("---", "", (body || "").trim());
  return lines.join("\n").trim();
}

export function toSpreadsheetColumnName(index) {
  let current = index + 1;
  let result = "";
  while (current > 0) {
    const remainder = (current - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    current = Math.floor((current - 1) / 26);
  }
  return result;
}

export function iconNameForArtifact(file) {
  const extension = (file?.extension || "").toLowerCase();
  if ([".xlsx", ".xls", ".csv"].includes(extension)) return "FileSpreadsheet";
  if ([".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".sql", ".sh"].includes(extension)) {
    return "FileCode2";
  }
  return "FileText";
}

export function rememberTheme(theme) {
  window.localStorage.setItem("demo-theme", theme);
}

export function readRememberedTheme() {
  return window.localStorage.getItem("demo-theme") || DEFAULT_THEME;
}

export function rememberLastThreadId(threadId) {
  if (!threadId) return;
  window.localStorage.setItem(LAST_THREAD_STORAGE_KEY, threadId);
}

export function readRememberedThreadId() {
  return window.localStorage.getItem(LAST_THREAD_STORAGE_KEY) || "";
}
