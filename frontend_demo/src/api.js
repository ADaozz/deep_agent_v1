import axios from "axios";

const http = axios.create({
  baseURL: "/",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});

function normalizeApiError(error) {
  if (error?.response?.data?.error) {
    return new Error(String(error.response.data.error));
  }
  if (error?.message) {
    return new Error(String(error.message));
  }
  return new Error("unknown_api_error");
}

http.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(normalizeApiError(error))
);

async function requestJson(config) {
  const response = await http.request(config);
  return response.data;
}

export const demoApi = {
  fetchMeta() {
    return requestJson({ url: "/api/demo/meta", method: "GET" });
  },
  fetchHistory(threadId = "") {
    return requestJson({
      url: threadId ? `/api/demo/history?thread_id=${encodeURIComponent(threadId)}` : "/api/demo/history",
      method: "GET",
    });
  },
  fetchHistoryThreads() {
    return requestJson({ url: "/api/demo/history/threads", method: "GET" });
  },
  deleteHistoryThread(threadId) {
    return requestJson({
      url: `/api/demo/history?thread_id=${encodeURIComponent(threadId)}`,
      method: "DELETE",
    });
  },
  fetchPrompts() {
    return requestJson({ url: "/api/demo/prompts", method: "GET" });
  },
  savePrompt(id, content) {
    return requestJson({
      url: "/api/demo/prompts",
      method: "POST",
      data: { id, content },
    });
  },
  resetPrompt(id) {
    return requestJson({
      url: "/api/demo/prompts/reset",
      method: "POST",
      data: { id },
    });
  },
  fetchSkills() {
    return requestJson({ url: "/api/demo/skills", method: "GET" });
  },
  saveSkill(id, content) {
    return requestJson({
      url: "/api/demo/skills",
      method: "POST",
      data: { id, content },
    });
  },
  resetSkill(id) {
    return requestJson({
      url: "/api/demo/skills/reset",
      method: "POST",
      data: { id },
    });
  },
  fetchTools() {
    return requestJson({ url: "/api/demo/tools", method: "GET" });
  },
  toggleTool(id, enabled) {
    return requestJson({
      url: "/api/demo/tools/toggle",
      method: "POST",
      data: { id, enabled },
    });
  },
  updateThreadState(payload) {
    return requestJson({
      url: "/api/demo/thread-state",
      method: "POST",
      data: payload,
    });
  },
  uploadUserFile(threadId, file, onProgress, signal) {
    const formData = new FormData();
    formData.append("thread_id", threadId);
    formData.append("user_file", file, file.name);
    return http.request({
      url: "/api/demo/user-file",
      method: "POST",
      data: formData,
      signal,
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (!event.total) return;
        onProgress?.(event.loaded, event.total);
      },
    }).then((response) => response.data);
  },
  deleteUserFile(path) {
    return requestJson({
      url: `/api/demo/user-file?path=${encodeURIComponent(path)}`,
      method: "DELETE",
    });
  },
  saveSessionDraft(payload) {
    return requestJson({
      url: "/api/demo/session-draft",
      method: "POST",
      data: payload,
    });
  },
  saveWorkspaceFile(path, content) {
    return requestJson({
      url: "/api/demo/workspace-file",
      method: "POST",
      data: { path, content },
    });
  },
};

export async function runDemoStream(payload, { signal, onEvent }) {
  const response = await fetch("/api/demo/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    let errorPayload = {};
    try {
      errorPayload = await response.json();
    } catch {
      errorPayload = {};
    }
    throw new Error(errorPayload.error || "backend_error");
  }

  const contentType = response.headers.get("content-type") || "";
  if (!response.body || !contentType.includes("application/x-ndjson")) {
    const payloadData = await response.json();
    onEvent?.({ type: "snapshot", payload: payloadData });
    return;
  }

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
      const trimmed = line.trim();
      if (!trimmed) continue;
      onEvent?.(JSON.parse(trimmed));
    }
  }

  if (buffer.trim()) {
    onEvent?.(JSON.parse(buffer.trim()));
  }
}
