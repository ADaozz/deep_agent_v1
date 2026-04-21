import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { icons } from "./icons.js";
import {
  ALLOWED_USER_FILE_EXTENSIONS,
  DEFAULT_UI_STATE,
  EMPTY_DELETE_CONFIRM,
  MAX_USER_FILE_COUNT,
  MAX_ROUNDS,
} from "./constants.js";
import {
  classifyArtifact,
  cloneBaseState,
  createThreadId,
  formatFileSize,
  normalizeUiState,
  pendingUploadTone,
  readRememberedTheme,
  readRememberedThreadId,
  statusClass,
  stepLabel,
  stepState,
} from "./utils.js";
import {
  ArtifactCardList,
  InfoCard,
  Modal,
  PendingUploadList,
  StatCard,
  StatusCard,
  ThemeSwitcher,
} from "./components/common.js";
import { HeartbeatCenter, HistoryCenter, PromptCenter, SkillCenter, ToolCenter } from "./components/centers.js";
import { FilePreviewContent, SessionTranscript } from "./components/transcript.js";
import { useUploads } from "./composables/useUploads.js";
import { useArtifacts } from "./composables/useArtifacts.js";
import { useCenters } from "./composables/useCenters.js";
import { useSessionRuntime } from "./composables/useSessionRuntime.js";
import { usePersistence } from "./composables/usePersistence.js";
import { demoApi } from "./api.js";

export default {
  name: "App",
  components: {
    ArtifactCardList,
    FilePreviewContent,
    HistoryCenter,
    HeartbeatCenter,
    InfoCard,
    Modal,
    PendingUploadList,
    PromptCenter,
    SessionTranscript,
    SkillCenter,
    StatCard,
    StatusCard,
    ThemeSwitcher,
    ToolCenter,
  },
  setup() {
    const fileInput = ref(null);
    const threadId = ref(readRememberedThreadId() || createThreadId());
    const loading = ref(false);
    const uiState = ref(
      normalizeUiState({
        ...DEFAULT_UI_STATE,
        theme: readRememberedTheme(),
      })
    );
    const demoState = ref(cloneBaseState());
    const history = ref([]);
    const error = ref("");
    const backendConnected = ref(null);
    const showSettingsModal = ref(false);
    const envVariables = ref([]);
    const envLoading = ref(false);
    const envSaving = ref(false);
    const envError = ref("");
    const envSaveFeedback = ref("");
    let healthTimer = null;

    const uploads = useUploads({ threadId, loading });
    const centers = useCenters({
      threadId,
      uiState,
      history,
      demoState,
      error,
      loading,
      clearPendingUserFiles: uploads.clearPendingUserFiles,
    });
    const artifacts = useArtifacts({ history, demoState, uiState });
    const runtime = useSessionRuntime({
      threadId,
      uiState,
      history,
      demoState,
      error,
      loading,
      pendingUserFiles: uploads.pendingUserFiles,
      uploadError: uploads.uploadError,
      clearPendingUserFiles: uploads.clearPendingUserFiles,
      loadMeta: centers.loadMeta,
    });
    const persistence = usePersistence({
      threadId,
      uiState,
      history,
    });

    onMounted(() => {
      void centers.loadMeta();
      void centers.loadHistory();
      void checkBackendHealth();
      healthTimer = window.setInterval(checkBackendHealth, 5000);
    });

    onBeforeUnmount(() => {
      if (healthTimer) {
        window.clearInterval(healthTimer);
        healthTimer = null;
      }
      persistence.disposePersistence();
      runtime.disposeRuntime();
      uploads.disposeUploads();
    });

    async function checkBackendHealth() {
      try {
        const payload = await demoApi.checkHealth();
        backendConnected.value = Boolean(payload?.ok);
      } catch {
        backendConnected.value = false;
      }
    }

    function setUiState(patch) {
      uiState.value = normalizeUiState({ ...uiState.value, ...patch });
    }

    function setTheme(theme) {
      setUiState({ theme });
    }

    function closePromptModal() {
      centers.closePromptModal();
    }

    function closeSkillModal() {
      centers.closeSkillModal();
    }

    function closeToolModal() {
      centers.closeToolModal();
    }

    function closeHeartbeatModal() {
      centers.closeHeartbeatModal();
    }

    function openSettingsModal() {
      showSettingsModal.value = true;
      void loadEnvSettings();
    }

    function closeSettingsModal() {
      showSettingsModal.value = false;
      envError.value = "";
      envSaveFeedback.value = "";
    }

    function closeHistoryModal() {
      centers.closeHistoryModal();
    }

    function closeArtifactModal() {
      setUiState({ showArtifactModal: false, activeArtifactPath: "" });
    }

    function openAgent(agent) {
      setUiState({ selectedAgentId: agent.id });
    }

    function closeAgentModal() {
      setUiState({ selectedAgentId: "" });
    }

    function openDeleteConfirm(threadIdToDelete) {
      centers.deleteConfirm.value = { open: true, threadId: threadIdToDelete };
    }

    function closeDeleteConfirm() {
      centers.deleteConfirm.value = { ...EMPTY_DELETE_CONFIRM };
    }

    function selectPrompt(promptId) {
      centers.selectPrompt(promptId);
    }

    function selectSkill(skillId) {
      centers.selectSkill(skillId);
    }

    function selectTool(toolId) {
      centers.selectTool(toolId);
    }

    function setQuery(value) {
      runtime.setQuery(value);
    }

    async function loadEnvSettings() {
      envLoading.value = true;
      envError.value = "";
      try {
        const payload = await demoApi.fetchEnv();
        envVariables.value = Array.isArray(payload.variables) ? payload.variables : [];
      } catch (exc) {
        envError.value = exc?.message || "环境变量加载失败";
      } finally {
        envLoading.value = false;
      }
    }

    function updateEnvValue(name, value) {
      envVariables.value = envVariables.value.map((item) =>
        item.name === name ? { ...item, value } : item
      );
      envSaveFeedback.value = "";
    }

    async function saveEnvSettings() {
      envSaving.value = true;
      envError.value = "";
      envSaveFeedback.value = "";
      try {
        const values = {};
        for (const item of envVariables.value) {
          values[item.name] = item.value || "";
        }
        const payload = await demoApi.saveEnv(values);
        envVariables.value = Array.isArray(payload.variables) ? payload.variables : envVariables.value;
        envSaveFeedback.value = "环境变量已保存";
        void centers.loadMeta();
      } catch (exc) {
        envError.value = exc?.message || "环境变量保存失败";
      } finally {
        envSaving.value = false;
      }
    }

    const interactionLocked = computed(() => loading.value);
    const envVariableGroups = computed(() => {
      const groups = [];
      const indexByName = new Map();
      for (const item of envVariables.value) {
        const groupName = item.group || "Other";
        if (!indexByName.has(groupName)) {
          indexByName.set(groupName, groups.length);
          groups.push({ name: groupName, variables: [] });
        }
        groups[indexByName.get(groupName)].variables.push(item);
      }
      return groups;
    });
    const backendBadgeClass = computed(() => {
      if (backendConnected.value === true) return "is-connected";
      if (backendConnected.value === false) return "is-disconnected";
      return "is-checking";
    });
    const backendBadgeTitle = computed(() => {
      if (backendConnected.value === true) return "后端已连通";
      if (backendConnected.value === false) return "后端未连通";
      return "正在检查后端连通状态";
    });

    return {
      activeArtifact: artifacts.activeArtifact,
      artifactDraft: artifacts.artifactDraft,
      artifactPreview: artifacts.artifactPreview,
      artifactPreviewKindPreview: artifacts.artifactPreviewKindPreview,
      artifactSaveFeedback: artifacts.artifactSaveFeedback,
      artifactSaving: artifacts.artifactSaving,
      classifyArtifact,
      closeAgentModal,
      closeArtifactModal,
      closeDeleteConfirm,
      closeHistoryModal,
      closeHeartbeatModal,
      closeSettingsModal,
      closePromptModal,
      closeSkillModal,
      closeToolModal,
      completedCount: runtime.completedCount,
      backendBadgeClass,
      backendBadgeTitle,
      deleteConfirm: centers.deleteConfirm,
      deletingThreadId: centers.deletingThreadId,
      deletingHeartbeatTaskId: centers.deletingHeartbeatTaskId,
      runningHeartbeatTaskId: centers.runningHeartbeatTaskId,
      demoState,
      error,
      fileInput,
      formatFileSize,
      handleChooseUserFile: () => uploads.handleChooseUserFile(fileInput),
      handleComposerKeyDown: runtime.handleComposerKeyDown,
      handleDeleteThread: centers.handleDeleteThread,
      handleDeleteHeartbeat: centers.handleDeleteHeartbeat,
      handleRunHeartbeatNow: centers.handleRunHeartbeatNow,
      handleNewThread: runtime.handleNewThread,
      handleOpenArtifact: artifacts.handleOpenArtifact,
      handlePendingFileChange: uploads.handlePendingFileChange,
      handleRemovePendingUserFile: uploads.handleRemovePendingUserFile,
      handleResetPrompt: centers.handleResetPrompt,
      handleResetSkill: centers.handleResetSkill,
      handleRun: runtime.handleRun,
      handleSaveArtifact: artifacts.handleSaveArtifact,
      handleSavePrompt: centers.handleSavePrompt,
      handleSaveSkill: centers.handleSaveSkill,
      handleSelectThread: centers.handleSelectThread,
      handleStop: runtime.handleStop,
      handleToggleTool: centers.handleToggleTool,
      handleToggleHeartbeat: centers.handleToggleHeartbeat,
      headerStatus: runtime.headerStatus,
      historyThreads: centers.historyThreads,
      historyThreadsError: centers.historyThreadsError,
      historyThreadsLoading: centers.historyThreadsLoading,
      heartbeatTasks: centers.heartbeatTasks,
      heartbeatRuns: centers.heartbeatRuns,
      heartbeatLoading: centers.heartbeatLoading,
      heartbeatError: centers.heartbeatError,
      heartbeatTogglingId: centers.heartbeatTogglingId,
      envError,
      envLoading,
      envSaveFeedback,
      envSaving,
      envVariables,
      envVariableGroups,
      icons,
      interactionLocked,
      isEditableArtifact: artifacts.isEditableArtifact,
      loading,
      MAX_USER_FILE_COUNT,
      MAX_ROUNDS,
      modelName: centers.modelName,
      openAgent,
      openDeleteConfirm,
      openHistoryCenter: centers.openHistoryCenter,
      openHeartbeatCenter: centers.openHeartbeatCenter,
      openPromptCenter: centers.openPromptCenter,
      openSettingsModal,
      openSkillCenter: centers.openSkillCenter,
      openToolCenter: centers.openToolCenter,
      pendingUploadTone,
      pendingUserFiles: uploads.pendingUserFiles,
      promptError: centers.promptError,
      promptLoading: centers.promptLoading,
      promptResetting: centers.promptResetting,
      promptSaveFeedback: centers.promptSaveFeedback,
      promptSaveFeedbackTone: centers.promptSaveFeedbackTone,
      promptSaving: centers.promptSaving,
      promptSections: centers.promptSections,
      runningCount: runtime.runningCount,
      selectHeartbeatTask: centers.selectHeartbeatTask,
      selectPrompt,
      selectSkill,
      selectTool,
      selectedAgent: runtime.selectedAgent,
      saveEnvSettings,
      setQuery,
      setTheme,
      skillError: centers.skillError,
      skillLoading: centers.skillLoading,
      skillResetting: centers.skillResetting,
      skillSaveFeedback: centers.skillSaveFeedback,
      skillSaveFeedbackTone: centers.skillSaveFeedbackTone,
      skillSaving: centers.skillSaving,
      showSettingsModal,
      skillSections: centers.skillSections,
      statusClass,
      stepLabel,
      stepState,
      threadId,
      toolError: centers.toolError,
      toolLoading: centers.toolLoading,
      toolSaveFeedback: centers.toolSaveFeedback,
      toolSaveFeedbackTone: centers.toolSaveFeedbackTone,
      toolSections: centers.toolSections,
      toolTogglingId: centers.toolTogglingId,
      uiState,
      updatePromptDraft: centers.updatePromptDraft,
      updateSkillDraft: centers.updateSkillDraft,
      updateEnvValue,
      uploadError: uploads.uploadError,
      workerCount: runtime.workerCount,
      activeSession: runtime.activeSession,
      history,
      ALLOWED_USER_FILE_EXTENSIONS,
    };
  },
  template: `
    <div class="app-shell">
      <aside class="side-rail">
        <div class="side-rail-card">
          <button type="button" :class="['side-menu-button', uiState.showHistoryModal ? 'is-active' : '']" title="查看历史会话" @click="openHistoryCenter">
            <component :is="icons.Clock3" class="h-4 w-4" />
            <span>历史</span>
          </button>
          <button type="button" :class="['side-menu-button', uiState.showPromptModal ? 'is-active' : '']" title="预览管理提示词" @click="openPromptCenter">
            <component :is="icons.BookText" class="h-4 w-4" />
            <span>提示词</span>
          </button>
          <button type="button" :class="['side-menu-button', uiState.showSkillModal ? 'is-active' : '']" title="预览管理 Skill" @click="openSkillCenter">
            <component :is="icons.Sparkles" class="h-4 w-4" />
            <span>Skill</span>
          </button>
          <button type="button" :class="['side-menu-button', uiState.showToolModal ? 'is-active' : '']" title="管理项目扩展工具" @click="openToolCenter">
            <component :is="icons.SlidersHorizontal" class="h-4 w-4" />
            <span>工具</span>
          </button>
          <button type="button" :class="['side-menu-button', uiState.showHeartbeatModal ? 'is-active' : '']" title="查看智能心跳任务" @click="openHeartbeatCenter">
            <component :is="icons.HeartPulse" class="h-4 w-4" />
            <span>智能心跳</span>
          </button>
        </div>
        <div class="side-rail-card side-rail-bottom">
          <button type="button" :class="['side-menu-button', showSettingsModal ? 'is-active' : '']" title="配置环境变量" @click="openSettingsModal">
            <component :is="icons.Settings" class="h-4 w-4" />
            <span>设置</span>
          </button>
        </div>
      </aside>
      <div class="dialog-shell">
        <header class="dialog-header">
          <div>
            <div :class="['app-badge', backendBadgeClass]" :title="backendBadgeTitle">
              <component :is="icons.TerminalSquare" class="h-4 w-4" />
              <span>Supervisor Agent Console</span>
            </div>
            <h1 class="dialog-title">多 Agent 执行工作台</h1>
            <p class="dialog-subtitle">用于拆解任务、调度 worker、跟踪执行过程，并汇总最终结果。</p>
          </div>
          <div class="header-side">
            <div class="header-actions">
              <button type="button" class="secondary-button" :disabled="loading" @click="handleNewThread">
                <component :is="icons.MessageSquare" class="h-4 w-4" />
                <span>新会话</span>
              </button>
            </div>
            <ThemeSwitcher :theme="uiState.theme" @change="setTheme" />
            <div class="thread-meta">thread_id: {{ threadId }}</div>
          </div>
        </header>

        <div class="stats-row">
          <StatCard :icon="icons.Activity" label="Current round" :value="demoState.current_round + ' / ' + (demoState.max_rounds || MAX_ROUNDS)" />
          <StatCard :icon="icons.ClipboardList" label="Action steps" :value="String(demoState.tasks.length)" />
          <StatCard :icon="icons.CheckCircle2" label="Completed" :value="String(completedCount)" />
          <StatCard :icon="icons.Bot" label="Active workers" :value="String(workerCount || runningCount)" />
          <StatusCard :icon="headerStatus.icon" label="状态" :value="headerStatus.label" :tone="headerStatus.tone" />
        </div>

        <main class="conversation-scroll">
          <template v-if="history.length">
            <SessionTranscript
              v-for="(session, index) in history"
              :key="session.id || index"
              :session="session"
              :error="session.error"
              @open-agent="openAgent"
              @open-file="handleOpenArtifact"
            />
          </template>
          <div v-else class="empty-thread">发送一条消息后，这里会按轮次保留完整问答记录。</div>
        </main>

        <div class="composer-dock">
          <div class="composer-stack">
            <div v-if="loading" class="composer-shell is-collapsed">
              <div class="composer-collapsed-note">
                <component :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
                <span>Supervisor 正在执行，对话框已收起</span>
              </div>
              <div class="composer-actions composer-actions-minimal">
                <button type="button" class="primary-button send-button stop-button" aria-label="停止执行" @click="handleStop">
                  <component :is="icons.Square" class="h-4 w-4" />
                </button>
              </div>
            </div>
            <template v-else>
              <div v-if="pendingUserFiles.length" class="composer-pending-overlay">
                <div class="pending-upload-panel">
                  <div class="pending-upload-header">
                    <span>待上传文件</span>
                    <span>{{ pendingUserFiles.length }}/{{ MAX_USER_FILE_COUNT }}</span>
                  </div>
                  <PendingUploadList :files="pendingUserFiles" @remove="handleRemovePendingUserFile" />
                </div>
              </div>
              <div class="composer-model-bubble">Model: {{ modelName || 'unknown' }}</div>
              <footer class="composer-shell">
                <input
                  ref="fileInput"
                  type="file"
                  class="hidden-file-input"
                  multiple
                  :accept="ALLOWED_USER_FILE_EXTENSIONS.join(',')"
                  @change="handlePendingFileChange"
                />
                <div class="composer-leading">
                  <button
                    type="button"
                    class="ghost-button upload-button"
                    aria-label="添加文件"
                    :disabled="loading || pendingUserFiles.length >= MAX_USER_FILE_COUNT"
                    @click="handleChooseUserFile"
                  >
                    <component :is="icons.Plus" class="h-4 w-4" />
                  </button>
                </div>
                <label class="composer-input-wrap" aria-label="User Query">
                  <span class="composer-label">User Query</span>
                  <textarea
                    :value="uiState.query"
                    class="composer-area"
                    placeholder="给 Supervisor 输入一个需要拆解并调度多 worker 的任务"
                    @input="setQuery($event.target.value)"
                    @keydown="handleComposerKeyDown"
                  ></textarea>
                  <div v-if="uploadError" class="composer-inline-error">{{ uploadError }}</div>
                </label>
                <div class="composer-actions composer-actions-minimal">
                  <button
                    type="button"
                    class="primary-button send-button"
                    aria-label="发送"
                    :disabled="loading || !uiState.query.trim() || pendingUserFiles.some((item) => item.status === 'uploading')"
                    @click="handleRun"
                  >
                    <component :is="icons.ArrowUp" class="h-4 w-4" />
                  </button>
                </div>
              </footer>
            </template>
          </div>
        </div>
      </div>

      <Modal :open="uiState.showPromptModal" title="管理提示词预览" eyebrow="提示词管理" variant="prompt-center" @close="closePromptModal">
        <PromptCenter
          :prompts="promptSections"
          :active-prompt-id="uiState.activePromptId"
          :loading="promptLoading"
          :error="promptError"
          :draft-content="uiState.promptDraft"
          :save-feedback="promptSaveFeedback"
          :save-feedback-tone="promptSaveFeedbackTone"
          :saving="promptSaving"
          :resetting="promptResetting"
          :read-only="loading"
          @select="selectPrompt"
          @update:draftContent="updatePromptDraft"
          @save="handleSavePrompt"
          @reset="handleResetPrompt"
        />
      </Modal>

      <Modal :open="uiState.showSkillModal" title="管理 Skill 预览" eyebrow="Skill 管理" variant="prompt-center" @close="closeSkillModal">
        <SkillCenter
          :skills="skillSections"
          :active-skill-id="uiState.activeSkillId"
          :loading="skillLoading"
          :error="skillError"
          :draft-content="uiState.skillDraft"
          :save-feedback="skillSaveFeedback"
          :save-feedback-tone="skillSaveFeedbackTone"
          :saving="skillSaving"
          :resetting="skillResetting"
          :read-only="loading"
          @select="selectSkill"
          @update:draftContent="updateSkillDraft"
          @save="handleSaveSkill"
          @reset="handleResetSkill"
        />
      </Modal>

      <Modal :open="uiState.showToolModal" title="工具控制" eyebrow="工具控制" variant="prompt-center" @close="closeToolModal">
        <ToolCenter
          :tools="toolSections"
          :active-tool-id="uiState.activeToolId"
          :toggling-tool-id="toolTogglingId"
          :loading="toolLoading"
          :error="toolError"
          :save-feedback="toolSaveFeedback"
          :save-feedback-tone="toolSaveFeedbackTone"
          @select="selectTool"
          @toggle="handleToggleTool"
        />
      </Modal>

      <Modal :open="uiState.showHeartbeatModal" title="智能心跳" eyebrow="Heartbeat" variant="heartbeat-center" @close="closeHeartbeatModal">
        <HeartbeatCenter
          :tasks="heartbeatTasks"
          :runs="heartbeatRuns"
          :active-task-id="uiState.activeHeartbeatTaskId"
          :loading="heartbeatLoading"
          :error="heartbeatError"
          :toggling-task-id="heartbeatTogglingId"
          :deleting-task-id="deletingHeartbeatTaskId"
          :running-task-id="runningHeartbeatTaskId"
          @select-task="selectHeartbeatTask"
          @toggle-task="handleToggleHeartbeat"
          @run-task="handleRunHeartbeatNow"
          @delete-task="handleDeleteHeartbeat"
        />
      </Modal>

      <Modal :open="uiState.showHistoryModal" title="历史会话" eyebrow="History" variant="prompt-center" @close="closeHistoryModal">
        <HistoryCenter
          :threads="historyThreads"
          :active-thread-id="threadId"
          :deleting-thread-id="deletingThreadId"
          :loading="historyThreadsLoading"
          :error="historyThreadsError"
          :interaction-locked="interactionLocked"
          @select-thread="handleSelectThread"
          @delete-thread="openDeleteConfirm"
        />
      </Modal>

      <Modal :open="showSettingsModal" title="环境变量配置" eyebrow="Settings" variant="env-center" @close="closeSettingsModal">
        <div class="env-settings-panel">
          <div v-if="envError" class="alert-block">{{ envError }}</div>
          <div v-if="envSaveFeedback" class="success-block">{{ envSaveFeedback }}</div>
          <div v-if="envLoading && !envVariables.length" class="empty-block">正在加载环境变量。</div>
          <div v-else class="env-group-stack">
            <section v-for="group in envVariableGroups" :key="group.name" class="env-group">
              <div class="message-section-title">
                <div class="message-section-heading">
                  <component :is="icons.Settings" class="h-4 w-4" />
                  <span>{{ group.name }}</span>
                </div>
                <span class="message-section-meta">{{ group.variables.length }} item(s)</span>
              </div>
              <div class="env-grid">
                <label v-for="variable in group.variables" :key="variable.name" class="form-field env-field">
                  <div class="form-label">{{ variable.label || variable.name }}</div>
                  <input
                    :type="variable.secret ? 'password' : 'text'"
                    class="field-control"
                    :value="variable.value"
                    :placeholder="variable.name"
                    :disabled="envSaving"
                    autocomplete="off"
                    spellcheck="false"
                    @input="updateEnvValue(variable.name, $event.target.value)"
                  />
                  <div class="form-feedback">
                    {{ variable.name }} · {{ variable.from_env_file ? '.env' : variable.from_process ? 'process only' : 'unset' }}
                  </div>
                </label>
              </div>
            </section>
          </div>
          <div class="prompt-toolbar env-toolbar">
            <span class="prompt-toolbar-note">留空并保存会从 .env 和当前服务进程中移除该变量。</span>
            <div class="prompt-toolbar-actions">
              <button type="button" class="secondary-button" :disabled="envSaving" @click="closeSettingsModal">取消</button>
              <button type="button" class="primary-button" :disabled="envSaving || envLoading" @click="saveEnvSettings">
                <component :is="envSaving ? icons.LoaderCircle : icons.CheckCircle2" class="h-4 w-4" :class="{ 'animate-spin': envSaving }" />
                <span>{{ envSaving ? '保存中' : '保存配置' }}</span>
              </button>
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        :open="uiState.showArtifactModal && Boolean(activeArtifact)"
        :title="activeArtifact ? (activeArtifact.title || activeArtifact.name) : '文件预览'"
        eyebrow="文件预览"
        variant="file-preview"
        @close="closeArtifactModal"
      >
        <div v-if="activeArtifact" class="stack-block file-preview-stack">
          <div class="prompt-meta-card">
            <div>
              <div class="summary-title">{{ activeArtifact.original_name || activeArtifact.name || activeArtifact.title }}</div>
              <div class="summary-subtitle">{{ activeArtifact.updated_at }}</div>
            </div>
            <span class="tag">{{ activeArtifact.extension || '(无后缀)' }}</span>
          </div>
          <div class="prompt-toolbar">
            <span class="prompt-toolbar-note">{{ formatFileSize(activeArtifact.size) }} · {{ activeArtifact.mime_type }}</span>
            <div class="prompt-toolbar-actions">
              <button v-if="isEditableArtifact" type="button" class="secondary-button" :disabled="artifactSaving" @click="handleSaveArtifact">
                <component v-if="artifactSaving" :is="icons.LoaderCircle" class="h-4 w-4 animate-spin" />
                <span>{{ artifactSaving ? '保存中' : '保存修改' }}</span>
              </button>
              <a :href="activeArtifact.download_url" class="primary-button" download>下载文件</a>
            </div>
          </div>
          <div v-if="artifactSaveFeedback" :class="artifactSaveFeedback.startsWith('保存失败') ? 'alert-block' : 'success-block'">{{ artifactSaveFeedback }}</div>
          <div v-if="isEditableArtifact" class="artifact-editor-grid">
            <label class="form-field artifact-editor-pane">
              <div class="form-label">编辑内容</div>
              <textarea class="field-control field-area prompt-editor artifact-editor" v-model="artifactDraft" spellcheck="false"></textarea>
            </label>
            <div class="stack-block artifact-preview-pane">
              <div class="form-label">预览</div>
              <FilePreviewContent :file="activeArtifact" :preview-state="artifactPreviewKindPreview" />
            </div>
          </div>
          <FilePreviewContent v-else :file="activeArtifact" :preview-state="artifactPreview" />
        </div>
        <div v-else class="empty-block">未找到文件产物。</div>
      </Modal>

      <Modal :open="Boolean(selectedAgent)" :title="selectedAgent ? selectedAgent.name + ' Metadata' : ''" @close="closeAgentModal">
        <div v-if="selectedAgent" class="detail-grid modal-grid">
          <InfoCard label="ID" :value="selectedAgent.id" />
          <InfoCard label="Name" :value="selectedAgent.name" />
          <InfoCard label="Scope" :value="selectedAgent.scope || selectedAgent.role || selectedAgent.description || '未定义'" :wide="true" />
          <InfoCard label="Role" :value="selectedAgent.role || '未定义'" />
          <InfoCard label="Status" :value="stepLabel(selectedAgent.status)" />
          <InfoCard label="Current task" :value="selectedAgent.current_task_title || '待命中'" :wide="true" />
          <InfoCard label="Description" :value="selectedAgent.description || '未提供'" :wide="true" />
          <InfoCard label="Recent report" :value="selectedAgent.report || '本轮尚未汇报'" :wide="true" />
          <InfoCard label="Guard" :value="selectedAgent.last_guard_message || '最近没有 guard 拦截'" :wide="true" />
        </div>
      </Modal>

      <Modal :open="deleteConfirm.open" title="删除历史线程" eyebrow="历史会话" variant="confirm" @close="closeDeleteConfirm">
        <div class="stack-block confirm-stack">
          <div class="note-block">该操作会删除这条线程下的全部会话历史和线程级 UI 状态，且无法恢复。</div>
          <div class="info-card wide">
            <div class="info-label">Thread ID</div>
            <div class="info-value">{{ deleteConfirm.threadId || '-' }}</div>
          </div>
          <div class="prompt-toolbar-actions confirm-actions">
            <button type="button" class="secondary-button" :disabled="Boolean(deletingThreadId)" @click="closeDeleteConfirm">取消</button>
            <button type="button" class="primary-button stop-button" :disabled="Boolean(deletingThreadId)" @click="handleDeleteThread(deleteConfirm.threadId)">
              <component :is="deletingThreadId ? icons.LoaderCircle : icons.Trash2" class="h-4 w-4" :class="{ 'animate-spin': Boolean(deletingThreadId) }" />
              <span>{{ deletingThreadId ? '删除中' : '确认删除' }}</span>
            </button>
          </div>
        </div>
      </Modal>
    </div>
  `,
};
