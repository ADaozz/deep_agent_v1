import { computed, ref } from "vue";

import { runDemoStream, demoApi } from "../api.js";
import { DEFAULT_UI_STATE, MAX_ROUNDS } from "../constants.js";
import {
  cloneBaseState,
  createThreadId,
  isActiveWorkerStatus,
  mergeSessionState,
  normalizeSessionState,
  normalizeUiState,
  stepState,
  validatePendingUserFile,
  writeCachedSessionUserFiles,
} from "../utils.js";
import { icons } from "../icons.js";

export function useSessionRuntime({
  threadId,
  uiState,
  history,
  demoState,
  error,
  loading: externalLoading,
  pendingUserFiles,
  uploadError,
  clearPendingUserFiles,
  loadMeta,
}) {
  const loading = externalLoading || ref(false);
  const runController = ref(null);

  const selectedAgent = computed(
    () => demoState.value.agents.find((agent) => agent.id === uiState.value.selectedAgentId) || null
  );
  const completedCount = computed(
    () => demoState.value.tasks.filter((task) => stepState(task.status) === "success").length
  );
  const runningCount = computed(
    () => demoState.value.tasks.filter((task) => stepState(task.status) === "running").length
  );
  const workerCount = computed(
    () => demoState.value.agents.filter((agent) => isActiveWorkerStatus(agent.status)).length
  );
  const headerStatus = computed(() => {
    if (error.value || demoState.value.status === "stopped") {
      return { label: "错误", icon: icons.ShieldAlert, tone: "error" };
    }
    if (demoState.value.status === "running") {
      return { label: "进行中", icon: icons.LoaderCircle, tone: "running" };
    }
    if (demoState.value.status === "done") {
      return { label: "已完成", icon: icons.CheckCircle2, tone: "success" };
    }
    return { label: "待命", icon: icons.Circle, tone: "pending" };
  });
  const activeSession = computed(
    () =>
      history.value[history.value.length - 1] || {
        id: "",
        query: demoState.value.query,
        state: demoState.value,
        error: error.value,
      }
  );

  async function handleRun() {
    const trimmed = uiState.value.query.trim();
    if (loading.value) return;
    if (!trimmed) {
      if (pendingUserFiles.value.length) uploadError.value = "仅上传文件不能发送，请先输入问题。";
      return;
    }

    for (const pendingFile of pendingUserFiles.value) {
      if (pendingFile.file) {
        const validationError = validatePendingUserFile(pendingFile.file);
        if (validationError) {
          uploadError.value = validationError;
          return;
        }
      } else if (!pendingFile.path) {
        uploadError.value = "存在未完成上传的文件，请移除后重试。";
        return;
      }
      if (pendingFile.status === "uploading") {
        uploadError.value = "仍有文件上传中，请等待完成后再发送。";
        return;
      }
      if (pendingFile.status === "error") {
        uploadError.value = "存在上传失败的文件，请移除后重试。";
        return;
      }
    }

    const sessionId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const messageHistory = history.value.flatMap((session) => {
      const items = [{ role: "user", content: session.query }];
      if (session.state.final_summary) items.push({ role: "assistant", content: session.state.final_summary });
      return items;
    });
    const localUserFiles = pendingUserFiles.value
      .filter((item) => item.path)
      .map((item) => ({ ...item, original_name: item.original_name || item.name }));

    loading.value = true;
    error.value = "";
    uploadError.value = "";
    const nextState = {
      ...cloneBaseState(),
      agents: demoState.value.agents,
      query: trimmed,
      user_files: localUserFiles,
      status: "running",
      scheduler_thought: "Supervisor 正在分析 query，准备建立本轮 Action List。",
    };
    const nextSessionRecord = { id: sessionId, query: trimmed, state: nextState, error: "" };
    demoState.value = nextState;
    history.value = [...history.value, nextSessionRecord];
    writeCachedSessionUserFiles(threadId.value, sessionId, localUserFiles);
    uiState.value = normalizeUiState({ ...uiState.value, query: "" });
    pendingUserFiles.value = [];

    try {
      await demoApi
        .saveSessionDraft({
          thread_id: threadId.value,
          session_id: sessionId,
          query: trimmed,
          payload: nextState,
        })
        .catch(() => {});

      const controller = new AbortController();
      runController.value = controller;
      await runDemoStream(
        {
          query: trimmed,
          thread_id: threadId.value,
          session_id: sessionId,
          max_rounds: MAX_ROUNDS,
          user_files: localUserFiles.map((item) => ({
            path: item.path,
            name: item.name,
            original_name: item.original_name || item.name,
          })),
          messages: [...messageHistory, { role: "user", content: trimmed }],
        },
        {
          signal: controller.signal,
          onEvent: (event) => {
            if (!event?.payload) return;
            const nextPayload = mergeSessionState(nextState, event.payload);
            demoState.value = nextPayload;
            history.value = history.value.map((item) =>
              item.id === sessionId
                ? {
                    ...item,
                    state: mergeSessionState(item.state, nextPayload),
                    error: event.type === "error" ? nextPayload.stop_reason || "执行失败。" : "",
                  }
                : item
            );
            if (event.type === "error") {
              error.value = nextPayload.stop_reason || "执行失败。";
            }
          },
        }
      );
    } catch (runError) {
      if (runError?.name === "AbortError") {
        const stoppedState = {
          ...nextState,
          status: "stopped",
          stop_reason: "Supervisor 已手动停止。",
          scheduler_thought: nextState.scheduler_thought || "执行已被手动中止。",
        };
        demoState.value = stoppedState;
        history.value = history.value.map((item) =>
          item.id === sessionId ? { ...item, state: stoppedState } : item
        );
        return;
      }
      const message =
        runError?.message === "query_required"
          ? "请输入问题后再发送。"
          : runError?.message || "后端接口不可用，请先运行 `python3 serve_demo.py`。";
      error.value = message;
      const failedState = {
        ...cloneBaseState(),
        agents: demoState.value.agents,
        query: trimmed,
        user_files: localUserFiles,
        status: "stopped",
        scheduler_thought: "未能拿到后端调度结果。",
        final_summary: "当前没有执行结果返回。",
      };
      demoState.value = failedState;
      history.value = history.value.map((item) =>
        item.id === sessionId ? { ...item, state: failedState, error: message } : item
      );
    } finally {
      runController.value = null;
      loading.value = false;
    }
  }

  function handleStop() {
    runController.value?.abort();
  }

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    void handleRun();
  }

  function setQuery(value) {
    uiState.value = normalizeUiState({ ...uiState.value, query: value });
  }

  async function handleNewThread() {
    runController.value?.abort();
    runController.value = null;
    void clearPendingUserFiles();
    loading.value = false;
    error.value = "";
    history.value = [];
    threadId.value = createThreadId();
    uiState.value = normalizeUiState({
      ...DEFAULT_UI_STATE,
      theme: uiState.value.theme,
      activePromptId: uiState.value.activePromptId,
      activeSkillId: uiState.value.activeSkillId,
      activeToolId: uiState.value.activeToolId,
      promptDraft: uiState.value.promptDraft,
      skillDraft: uiState.value.skillDraft,
    });
    demoState.value = cloneBaseState();
    void loadMeta();
  }

  function disposeRuntime() {
    runController.value?.abort();
  }

  return {
    activeSession,
    completedCount,
    handleComposerKeyDown,
    handleNewThread,
    handleRun,
    handleStop,
    headerStatus,
    loading,
    runningCount,
    selectedAgent,
    setQuery,
    workerCount,
    disposeRuntime,
  };
}
