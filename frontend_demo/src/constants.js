export const MAX_ROUNDS = 12;
export const DEFAULT_THEME = "vscode-light";
export const DEFAULT_QUERY = "";
export const MAX_USER_FILE_SIZE = 10 * 1024;
export const MAX_USER_FILE_COUNT = 3;
export const ALLOWED_USER_FILE_EXTENSIONS = [".md", ".xlsx", ".csv", ".txt", ".py"];
export const LAST_THREAD_STORAGE_KEY = "demo-last-thread-id";
export const HISTORY_CACHE_PREFIX = "demo-history-cache:";
export const SESSION_USER_FILES_CACHE_PREFIX = "demo-session-user-files:";

export const THEMES = [
  { id: "vscode-light", label: "VS Code Light", icon: "MonitorCog" },
  { id: "vscode-hc", label: "High Contrast", icon: "Contrast" },
];

export const EMPTY_STATE = {
  query: DEFAULT_QUERY,
  max_rounds: MAX_ROUNDS,
  execution_mode: "divide_and_conquer",
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
  loaded_skills: [],
  logs: [],
};

export const DEFAULT_UI_STATE = {
  theme: DEFAULT_THEME,
  query: DEFAULT_QUERY,
  showPromptModal: false,
  showSkillModal: false,
  showHistoryModal: false,
  showToolModal: false,
  showHeartbeatModal: false,
  showArtifactModal: false,
  activePromptId: "",
  activeSkillId: "",
  activeToolId: "",
  activeHeartbeatTaskId: "",
  promptDraft: "",
  skillDraft: "",
  selectedAgentId: "",
  activeArtifactPath: "",
};

export const EMPTY_DELETE_CONFIRM = {
  open: false,
  threadId: "",
};
