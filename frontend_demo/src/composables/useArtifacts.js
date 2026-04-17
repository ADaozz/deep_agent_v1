import { computed, ref, watch } from "vue";
import { marked } from "marked";
import DOMPurify from "dompurify";

import { demoApi } from "../api.js";
import { classifyArtifact, normalizeUiState } from "../utils.js";

async function readPreviewResponse(response, kind) {
  if (!response.ok) {
    throw new Error(`预览加载失败: HTTP ${response.status}`);
  }
  return kind === "spreadsheet" ? response.json() : response.text();
}

function renderMarkdown(markdown) {
  return DOMPurify.sanitize(marked.parse(markdown, { gfm: true, breaks: true }), {
    USE_PROFILES: { html: true },
  });
}

export function useArtifacts({ history, demoState, uiState }) {
  const artifactPreview = ref({ loading: false, error: "", text: "", html: "", spreadsheet: null });
  const artifactDraft = ref("");
  const artifactSaving = ref(false);
  const artifactSaveFeedback = ref("");
  const artifactSelection = ref({ path: "", originalName: "", name: "" });

  const publishedFiles = computed(() => {
    const items = new Map();
    for (const session of history.value) {
      for (const file of session.state?.files || []) {
        if (file?.path) items.set(file.path, file);
      }
      for (const file of session.state?.user_files || []) {
        if (file?.path) items.set(file.path, file);
      }
    }
    return Array.from(items.values());
  });

  const activeArtifact = computed(
    () => publishedFiles.value.find((file) => file.path === uiState.value.activeArtifactPath) || null
  );
  const activeArtifactKind = computed(() => (activeArtifact.value ? classifyArtifact(activeArtifact.value) : ""));
  const isEditableArtifact = computed(
    () =>
      Boolean(activeArtifact.value) &&
      ["markdown", "text"].includes(activeArtifactKind.value) &&
      activeArtifact.value.source !== "user_upload"
  );

  const artifactPreviewKindPreview = computed(() => {
    if (!activeArtifact.value) return artifactPreview.value;
    if (activeArtifactKind.value === "markdown") {
      return {
        ...artifactPreview.value,
        text: artifactDraft.value,
        html: renderMarkdown(artifactDraft.value),
      };
    }
    if (activeArtifactKind.value === "text") {
      return { ...artifactPreview.value, text: artifactDraft.value };
    }
    return artifactPreview.value;
  });

  watch(
    publishedFiles,
    (nextFiles) => {
      if (!uiState.value.showArtifactModal || activeArtifact.value || !uiState.value.activeArtifactPath) return;
      const remembered = artifactSelection.value;
      const matched = nextFiles.find(
        (file) =>
          (remembered.originalName && (file.original_name || file.name) === remembered.originalName) ||
          (remembered.name && file.name === remembered.name)
      );
      if (matched?.path && matched.path !== uiState.value.activeArtifactPath) {
        uiState.value = normalizeUiState({ ...uiState.value, activeArtifactPath: matched.path });
      }
    },
    { deep: true }
  );

  watch(
    activeArtifact,
    async (file) => {
      if (!uiState.value.showArtifactModal || !file) {
        artifactPreview.value = { loading: false, error: "", text: "", html: "", spreadsheet: null };
        artifactDraft.value = "";
        artifactSaveFeedback.value = "";
        return;
      }
      const kind = activeArtifactKind.value;
      if (!["markdown", "text", "spreadsheet"].includes(kind)) {
        artifactPreview.value = { loading: false, error: "", text: "", html: "", spreadsheet: null };
        artifactDraft.value = "";
        return;
      }
      artifactPreview.value = { loading: true, error: "", text: "", html: "", spreadsheet: null };
      artifactDraft.value = "";
      artifactSaveFeedback.value = "";
      try {
        const previewTarget =
          kind === "spreadsheet"
            ? file.preview_json_url || `${file.preview_url}${file.preview_url.includes("?") ? "&" : "?"}format=json`
            : file.preview_url;
        const payload = await readPreviewResponse(await fetch(previewTarget), kind);
        if (kind === "spreadsheet") {
          artifactPreview.value = { loading: false, error: "", text: "", html: "", spreadsheet: payload };
          return;
        }
        const text = payload;
        if (kind === "markdown") {
          artifactPreview.value = {
            loading: false,
            error: "",
            text,
            html: renderMarkdown(text),
            spreadsheet: null,
          };
          artifactDraft.value = text;
          return;
        }
        artifactPreview.value = { loading: false, error: "", text, html: "", spreadsheet: null };
        artifactDraft.value = text;
      } catch (loadError) {
        artifactPreview.value = {
          loading: false,
          error: loadError.message,
          text: "",
          html: "",
          spreadsheet: null,
        };
      }
    },
    { immediate: true }
  );

  function handleOpenArtifact(file) {
    artifactSelection.value = {
      path: file?.path || "",
      originalName: file?.original_name || file?.name || "",
      name: file?.name || "",
    };
    uiState.value = normalizeUiState({
      ...uiState.value,
      activeArtifactPath: file?.path || "",
      showArtifactModal: Boolean(file?.path),
    });
  }

  async function handleSaveArtifact() {
    if (!activeArtifact.value || artifactSaving.value) return;
    artifactSaving.value = true;
    artifactSaveFeedback.value = "";
    try {
      const payload = await demoApi.saveWorkspaceFile(activeArtifact.value.path, artifactDraft.value);
      const nextFile = payload.file || activeArtifact.value;
      const syncFiles = (files = []) =>
        files.map((item) => (item.path === nextFile.path ? { ...item, ...nextFile } : item));
      demoState.value = { ...demoState.value, files: syncFiles(demoState.value.files || []) };
      history.value = history.value.map((session) => ({
        ...session,
        state: { ...session.state, files: syncFiles(session.state.files || []) },
      }));
      if (classifyArtifact(nextFile) === "markdown") {
        artifactPreview.value = {
          loading: false,
          error: "",
          text: artifactDraft.value,
          html: renderMarkdown(artifactDraft.value),
          spreadsheet: null,
        };
      } else if (classifyArtifact(nextFile) === "text") {
        artifactPreview.value = {
          loading: false,
          error: "",
          text: artifactDraft.value,
          html: "",
          spreadsheet: null,
        };
      }
      artifactSaveFeedback.value = "文件已保存。";
    } catch (error) {
      artifactSaveFeedback.value = `保存失败: ${error.message}`;
    } finally {
      artifactSaving.value = false;
    }
  }

  return {
    artifactDraft,
    artifactPreview,
    artifactPreviewKindPreview,
    artifactSaveFeedback,
    artifactSaving,
    artifactSelection,
    activeArtifact,
    activeArtifactKind,
    isEditableArtifact,
    publishedFiles,
    handleOpenArtifact,
    handleSaveArtifact,
  };
}
