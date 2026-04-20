import { ref } from "vue";

import { demoApi } from "../api.js";
import { EMPTY_DELETE_CONFIRM } from "../constants.js";
import {
  buildRawSkillDocument,
  cloneBaseState,
  createThreadId,
  hydrateSessionUserFiles,
  mergeSessionState,
  normalizeSessionState,
  normalizeUiState,
  readCachedThreadHistory,
  removeCachedSessionUserFilesForThread,
} from "../utils.js";

export function useCenters({
  threadId,
  uiState,
  history,
  demoState,
  error,
  loading,
  clearPendingUserFiles,
}) {
  const modelName = ref("");

  const promptSections = ref([]);
  const promptLoading = ref(false);
  const promptError = ref("");
  const promptSaving = ref(false);
  const promptResetting = ref(false);
  const promptSaveFeedback = ref("");
  const promptSaveFeedbackTone = ref("");

  const skillSections = ref([]);
  const skillLoading = ref(false);
  const skillError = ref("");
  const skillSaving = ref(false);
  const skillResetting = ref(false);
  const skillSaveFeedback = ref("");
  const skillSaveFeedbackTone = ref("");
  let skillFeedbackTimer = 0;

  const toolSections = ref([]);
  const toolLoading = ref(false);
  const toolError = ref("");
  const toolTogglingId = ref("");
  const toolSaveFeedback = ref("");
  const toolSaveFeedbackTone = ref("");

  const heartbeatTasks = ref([]);
  const heartbeatRuns = ref([]);
  const heartbeatLoading = ref(false);
  const heartbeatError = ref("");
  const heartbeatTogglingId = ref("");
  const deletingHeartbeatTaskId = ref("");
  const runningHeartbeatTaskId = ref("");
  let heartbeatRefreshTimer = 0;

  const historyThreads = ref([]);
  const historyThreadsLoading = ref(false);
  const historyThreadsError = ref("");
  const deletingThreadId = ref("");
  const deleteConfirm = ref({ ...EMPTY_DELETE_CONFIRM });

  function clearSkillFeedback() {
    if (skillFeedbackTimer) {
      globalThis.clearTimeout(skillFeedbackTimer);
      skillFeedbackTimer = 0;
    }
    skillSaveFeedback.value = "";
    skillSaveFeedbackTone.value = "";
  }

  function showSkillFeedback(message, tone) {
    clearSkillFeedback();
    skillSaveFeedback.value = message;
    skillSaveFeedbackTone.value = tone;
    if (tone === "success") {
      skillFeedbackTimer = globalThis.setTimeout(() => {
        skillSaveFeedback.value = "";
        skillSaveFeedbackTone.value = "";
        skillFeedbackTimer = 0;
      }, 2200);
    }
  }

  async function loadMeta() {
    try {
      const payload = await demoApi.fetchMeta();
      modelName.value = payload.model || "";
      demoState.value = {
        ...demoState.value,
        agents: (payload.agents || []).map((agent) => agent),
      };
    } catch {}
  }

  async function loadHistory() {
    try {
      const cachedThreadId = threadId.value;
      const cachedSessions = readCachedThreadHistory(cachedThreadId);
      const payload = await demoApi.fetchHistory(cachedThreadId);
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
      if (payload.thread_id) threadId.value = payload.thread_id;
      uiState.value = normalizeUiState({
        ...uiState.value,
        ...(payload.ui_state || {}),
        showPromptModal: false,
        showSkillModal: false,
        showHistoryModal: false,
        showToolModal: false,
        showArtifactModal: false,
      });
      await clearPendingUserFiles();
      if (mergedSessions.length) {
        history.value = mergedSessions;
        const lastSession = mergedSessions[mergedSessions.length - 1];
        demoState.value = normalizeSessionState(lastSession.state);
        error.value = lastSession.error || "";
      } else {
        history.value = [];
        demoState.value = cloneBaseState();
        error.value = "";
      }
    } catch {}
  }

  async function loadHistoryThreads() {
    historyThreadsLoading.value = true;
    historyThreadsError.value = "";
    try {
      const payload = await demoApi.fetchHistoryThreads();
      historyThreads.value = Array.isArray(payload.threads) ? payload.threads : [];
    } catch (loadError) {
      historyThreadsError.value = `加载历史线程失败: ${loadError.message}`;
    } finally {
      historyThreadsLoading.value = false;
    }
  }

  async function loadPrompts() {
    promptLoading.value = true;
    promptError.value = "";
    try {
      const payload = await demoApi.fetchPrompts();
      const prompts = Array.isArray(payload.prompts) ? payload.prompts : [];
      promptSections.value = prompts;
      const nextId = uiState.value.activePromptId || prompts[0]?.id || "";
      const matched = prompts.find((item) => item.id === nextId) || prompts[0];
      uiState.value = normalizeUiState({
        ...uiState.value,
        activePromptId: nextId,
        promptDraft: matched?.content || "",
      });
    } catch (loadError) {
      promptError.value = `加载提示词失败: ${loadError.message}`;
    } finally {
      promptLoading.value = false;
    }
  }

  async function loadSkills() {
    skillLoading.value = true;
    skillError.value = "";
    clearSkillFeedback();
    try {
      const payload = await demoApi.fetchSkills();
      const skills = Array.isArray(payload.skills) ? payload.skills : [];
      skillSections.value = skills;
      const nextId = uiState.value.activeSkillId || skills[0]?.id || "";
      const matched = skills.find((item) => item.id === nextId) || skills[0];
      uiState.value = normalizeUiState({
        ...uiState.value,
        activeSkillId: nextId,
        skillDraft: matched?.body || "",
      });
    } catch (loadError) {
      skillError.value = `加载 skill 失败: ${loadError.message}`;
    } finally {
      skillLoading.value = false;
    }
  }

  async function loadTools() {
    toolLoading.value = true;
    toolError.value = "";
    try {
      const payload = await demoApi.fetchTools();
      const tools = Array.isArray(payload.tools) ? payload.tools : [];
      toolSections.value = tools;
      uiState.value = normalizeUiState({
        ...uiState.value,
        activeToolId: uiState.value.activeToolId || tools[0]?.id || "",
      });
    } catch (loadError) {
      toolError.value = `加载工具列表失败: ${loadError.message}`;
    } finally {
      toolLoading.value = false;
    }
  }

  async function loadHeartbeats(taskId = "") {
    heartbeatLoading.value = true;
    heartbeatError.value = "";
    try {
      const payload = await demoApi.fetchHeartbeats(taskId);
      heartbeatTasks.value = Array.isArray(payload.tasks) ? payload.tasks : [];
      heartbeatRuns.value = Array.isArray(payload.runs) ? payload.runs : [];
      const nextId = taskId || uiState.value.activeHeartbeatTaskId || heartbeatTasks.value[0]?.task_id || "";
      const activeTask = heartbeatTasks.value.find((item) => item.task_id === nextId);
      if (!activeTask || String(activeTask.status || "").toLowerCase() !== "running") {
        runningHeartbeatTaskId.value = "";
      }
      uiState.value = normalizeUiState({
        ...uiState.value,
        activeHeartbeatTaskId: nextId,
      });
    } catch (loadError) {
      heartbeatError.value = `加载智能心跳失败: ${loadError.message}`;
    } finally {
      heartbeatLoading.value = false;
    }
  }

  function clearHeartbeatRefreshTimer() {
    if (heartbeatRefreshTimer) {
      globalThis.clearTimeout(heartbeatRefreshTimer);
      heartbeatRefreshTimer = 0;
    }
  }

  function scheduleHeartbeatRefresh(taskId, remaining = 120) {
    clearHeartbeatRefreshTimer();
    if (!taskId || remaining <= 0) return;
    heartbeatRefreshTimer = globalThis.setTimeout(async () => {
      heartbeatRefreshTimer = 0;
      await loadHeartbeats(taskId);
      const activeTask = heartbeatTasks.value.find((item) => item.task_id === taskId);
      if (activeTask && String(activeTask.status || "").toLowerCase() === "running") {
        runningHeartbeatTaskId.value = taskId;
        scheduleHeartbeatRefresh(taskId, remaining - 1);
      } else if (runningHeartbeatTaskId.value === taskId) {
        runningHeartbeatTaskId.value = "";
      }
    }, 3000);
  }

  function openPromptCenter() {
    uiState.value = normalizeUiState({ ...uiState.value, showPromptModal: true });
    if (!promptSections.value.length && !promptLoading.value) void loadPrompts();
  }

  function openSkillCenter() {
    clearSkillFeedback();
    uiState.value = normalizeUiState({ ...uiState.value, showSkillModal: true });
    if (!skillSections.value.length && !skillLoading.value) void loadSkills();
  }

  function openToolCenter() {
    uiState.value = normalizeUiState({ ...uiState.value, showToolModal: true });
    if (!toolSections.value.length && !toolLoading.value) void loadTools();
  }

  function openHeartbeatCenter() {
    uiState.value = normalizeUiState({ ...uiState.value, showHeartbeatModal: true });
    if (!heartbeatLoading.value) {
      void loadHeartbeats(uiState.value.activeHeartbeatTaskId || "");
    }
  }

  function openHistoryCenter() {
    uiState.value = normalizeUiState({ ...uiState.value, showHistoryModal: true });
    if (!historyThreads.value.length && !historyThreadsLoading.value) void loadHistoryThreads();
  }

  async function handleSavePrompt() {
    const targetId = uiState.value.activePromptId;
    if (!targetId || promptSaving.value) return;
    promptSaving.value = true;
    try {
      const payload = await demoApi.savePrompt(targetId, uiState.value.promptDraft);
      promptSections.value = Array.isArray(payload.prompts) ? payload.prompts : promptSections.value;
      promptSaveFeedback.value = "提示词已保存。";
      promptSaveFeedbackTone.value = "success";
    } catch (saveError) {
      promptSaveFeedback.value = `保存失败: ${saveError.message}`;
      promptSaveFeedbackTone.value = "error";
    } finally {
      promptSaving.value = false;
    }
  }

  async function handleResetPrompt() {
    const targetId = uiState.value.activePromptId;
    if (!targetId || promptResetting.value) return;
    promptResetting.value = true;
    try {
      const payload = await demoApi.resetPrompt(targetId);
      promptSections.value = Array.isArray(payload.prompts) ? payload.prompts : promptSections.value;
      const matched = (payload.prompts || []).find((item) => item.id === targetId);
      uiState.value = normalizeUiState({ ...uiState.value, promptDraft: matched?.content || "" });
      promptSaveFeedback.value = "已恢复默认提示词。";
      promptSaveFeedbackTone.value = "success";
    } catch (resetError) {
      promptSaveFeedback.value = `恢复失败: ${resetError.message}`;
      promptSaveFeedbackTone.value = "error";
    } finally {
      promptResetting.value = false;
    }
  }

  async function handleSaveSkill() {
    const targetId = uiState.value.activeSkillId;
    if (!targetId || skillSaving.value) return;
    skillSaving.value = true;
    try {
      const activeSkill = skillSections.value.find((item) => item.id === targetId);
      const rawContent = buildRawSkillDocument(activeSkill?.frontmatter || {}, uiState.value.skillDraft);
      const payload = await demoApi.saveSkill(targetId, rawContent);
      skillSections.value = Array.isArray(payload.skills) ? payload.skills : skillSections.value;
      showSkillFeedback("Skill 已保存。", "success");
    } catch (saveError) {
      showSkillFeedback(`保存失败: ${saveError.message}`, "error");
    } finally {
      skillSaving.value = false;
    }
  }

  async function handleResetSkill() {
    const targetId = uiState.value.activeSkillId;
    if (!targetId || skillResetting.value) return;
    skillResetting.value = true;
    try {
      const payload = await demoApi.resetSkill(targetId);
      skillSections.value = Array.isArray(payload.skills) ? payload.skills : skillSections.value;
      const matched = (payload.skills || []).find((item) => item.id === targetId);
      uiState.value = normalizeUiState({ ...uiState.value, skillDraft: matched?.body || "" });
      showSkillFeedback("已恢复默认 Skill。", "success");
    } catch (resetError) {
      showSkillFeedback(`恢复失败: ${resetError.message}`, "error");
    } finally {
      skillResetting.value = false;
    }
  }

  async function handleToggleTool(toolId, enabled) {
    if (!toolId || toolTogglingId.value) return;
    toolTogglingId.value = toolId;
    try {
      const payload = await demoApi.toggleTool(toolId, enabled);
      toolSections.value = Array.isArray(payload.tools) ? payload.tools : toolSections.value;
      toolSaveFeedback.value = enabled ? "工具已启用，后续新建的 agent 可见。" : "工具已关闭，后续新建的 agent 将不可见。";
      toolSaveFeedbackTone.value = "success";
    } catch (toggleError) {
      toolSaveFeedback.value = `切换失败: ${toggleError.message}`;
      toolSaveFeedbackTone.value = "error";
    } finally {
      toolTogglingId.value = "";
    }
  }

  async function handleToggleHeartbeat(taskId, enabled) {
    if (!taskId || heartbeatTogglingId.value) return;
    heartbeatTogglingId.value = taskId;
    heartbeatError.value = "";
    try {
      const payload = await demoApi.toggleHeartbeat(taskId, enabled);
      heartbeatTasks.value = Array.isArray(payload.tasks) ? payload.tasks : heartbeatTasks.value;
    } catch (toggleError) {
      heartbeatError.value = `切换智能心跳失败: ${toggleError.message}`;
    } finally {
      heartbeatTogglingId.value = "";
    }
  }

  async function handleRunHeartbeatNow(taskId) {
    if (!taskId || runningHeartbeatTaskId.value) return;
    runningHeartbeatTaskId.value = taskId;
    heartbeatError.value = "";
    try {
      const payload = await demoApi.runHeartbeatNow(taskId);
      heartbeatTasks.value = Array.isArray(payload.tasks) ? payload.tasks : heartbeatTasks.value;
      heartbeatRuns.value = Array.isArray(payload.runs) ? payload.runs : heartbeatRuns.value;
      uiState.value = normalizeUiState({
        ...uiState.value,
        activeHeartbeatTaskId: taskId,
      });
      scheduleHeartbeatRefresh(taskId);
    } catch (runError) {
      heartbeatError.value = `执行智能心跳测试失败: ${runError.message}`;
      runningHeartbeatTaskId.value = "";
    }
  }

  async function handleSelectThread(nextThreadId) {
    if (!nextThreadId || nextThreadId === threadId.value) {
      uiState.value = normalizeUiState({ ...uiState.value, showHistoryModal: false });
      return;
    }
    await clearPendingUserFiles();
    try {
      const payload = await demoApi.fetchHistory(nextThreadId);
      const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      const normalizedSessions = sessions.map((session) => ({
        id: session.id,
        query: session.query || "",
        state: mergeSessionState(cloneBaseState(), session.state),
        error: session.error || "",
      }));
      threadId.value = payload.thread_id || nextThreadId;
      uiState.value = normalizeUiState({
        ...uiState.value,
        ...(payload.ui_state || {}),
        showPromptModal: false,
        showSkillModal: false,
        showHistoryModal: false,
      });
      history.value = normalizedSessions.map((session) => hydrateSessionUserFiles(threadId.value, session));
      if (history.value.length) {
        const lastSession = history.value[history.value.length - 1];
        demoState.value = normalizeSessionState(lastSession.state);
        error.value = lastSession.error || "";
      } else {
        demoState.value = cloneBaseState();
        error.value = "";
      }
    } catch (selectError) {
      historyThreadsError.value = `切换历史线程失败: ${selectError.message}`;
    }
  }

  async function handleDeleteThread(targetThreadId) {
    if (!targetThreadId || deletingThreadId.value) return;
    deletingThreadId.value = targetThreadId;
    try {
      const payload = await demoApi.deleteHistoryThread(targetThreadId);
      historyThreads.value = historyThreads.value.filter((thread) => thread.thread_id !== targetThreadId);
      removeCachedSessionUserFilesForThread(targetThreadId);
      if (threadId.value !== targetThreadId) return;
      if (payload.latest_thread_id) {
        await handleSelectThread(payload.latest_thread_id);
        return;
      }
      threadId.value = createThreadId();
      history.value = [];
      error.value = "";
      demoState.value = cloneBaseState();
    } catch (deleteError) {
      historyThreadsError.value = `删除历史线程失败: ${deleteError.message}`;
    } finally {
      deletingThreadId.value = "";
      deleteConfirm.value = { ...EMPTY_DELETE_CONFIRM };
    }
  }

  async function handleDeleteHeartbeat(taskId) {
    if (!taskId || deletingHeartbeatTaskId.value) return;
    deletingHeartbeatTaskId.value = taskId;
    heartbeatError.value = "";
    try {
      await demoApi.deleteHeartbeat(taskId);
      heartbeatTasks.value = heartbeatTasks.value.filter((item) => item.task_id !== taskId);
      heartbeatRuns.value = [];
      if (uiState.value.activeHeartbeatTaskId === taskId) {
        uiState.value = normalizeUiState({
          ...uiState.value,
          activeHeartbeatTaskId: heartbeatTasks.value[0]?.task_id || "",
        });
      }
    } catch (deleteError) {
      heartbeatError.value = `删除智能心跳失败: ${deleteError.message}`;
    } finally {
      deletingHeartbeatTaskId.value = "";
    }
  }

  function selectPrompt(promptId) {
    uiState.value = normalizeUiState({
      ...uiState.value,
      activePromptId: promptId,
      promptDraft: promptSections.value.find((item) => item.id === promptId)?.content || "",
    });
  }

  function updatePromptDraft(content) {
    uiState.value = normalizeUiState({ ...uiState.value, promptDraft: content });
  }

  function selectSkill(skillId) {
    clearSkillFeedback();
    uiState.value = normalizeUiState({
      ...uiState.value,
      activeSkillId: skillId,
      skillDraft: skillSections.value.find((item) => item.id === skillId)?.body || "",
    });
  }

  function updateSkillDraft(content) {
    clearSkillFeedback();
    uiState.value = normalizeUiState({ ...uiState.value, skillDraft: content });
  }

  function selectTool(toolId) {
    uiState.value = normalizeUiState({ ...uiState.value, activeToolId: toolId });
  }

  function selectHeartbeatTask(taskId) {
    uiState.value = normalizeUiState({ ...uiState.value, activeHeartbeatTaskId: taskId });
    void loadHeartbeats(taskId);
  }

  function closePromptModal() {
    uiState.value = normalizeUiState({ ...uiState.value, showPromptModal: false });
  }

  function closeSkillModal() {
    clearSkillFeedback();
    uiState.value = normalizeUiState({ ...uiState.value, showSkillModal: false });
  }

  function closeToolModal() {
    uiState.value = normalizeUiState({ ...uiState.value, showToolModal: false });
  }

  function closeHeartbeatModal() {
    clearHeartbeatRefreshTimer();
    uiState.value = normalizeUiState({ ...uiState.value, showHeartbeatModal: false });
  }

  function closeHistoryModal() {
    uiState.value = normalizeUiState({ ...uiState.value, showHistoryModal: false });
  }

  return {
    deleteConfirm,
    deletingThreadId,
    historyThreads,
    historyThreadsError,
    historyThreadsLoading,
    loadHistory,
    loadHistoryThreads,
    loadMeta,
    loadHeartbeats,
    loadPrompts,
    loadSkills,
    loadTools,
    modelName,
    openHistoryCenter,
    openHeartbeatCenter,
    openPromptCenter,
    openSkillCenter,
    openToolCenter,
    heartbeatTasks,
    heartbeatRuns,
    heartbeatLoading,
    heartbeatError,
    heartbeatTogglingId,
    deletingHeartbeatTaskId,
    runningHeartbeatTaskId,
    promptError,
    promptLoading,
    promptResetting,
    promptSaveFeedback,
    promptSaveFeedbackTone,
    promptSaving,
    promptSections,
    skillError,
    skillLoading,
    skillResetting,
    skillSaveFeedback,
    skillSaveFeedbackTone,
    skillSaving,
    skillSections,
    toolError,
    toolLoading,
    toolSaveFeedback,
    toolSaveFeedbackTone,
    toolSections,
    toolTogglingId,
    handleDeleteHeartbeat,
    handleRunHeartbeatNow,
    handleDeleteThread,
    handleResetPrompt,
    handleResetSkill,
    handleSavePrompt,
    handleSaveSkill,
    handleSelectThread,
    handleToggleHeartbeat,
    handleToggleTool,
    selectHeartbeatTask,
    selectPrompt,
    selectSkill,
    selectTool,
    updatePromptDraft,
    updateSkillDraft,
    closePromptModal,
    closeSkillModal,
    closeToolModal,
    closeHeartbeatModal,
    closeHistoryModal,
  };
}
