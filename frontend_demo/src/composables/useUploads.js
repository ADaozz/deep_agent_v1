import { ref } from "vue";

import { MAX_USER_FILE_COUNT } from "../constants.js";
import { demoApi } from "../api.js";
import {
  createPendingUserFile,
  validatePendingUserFile,
} from "../utils.js";

export function useUploads({ threadId, loading }) {
  const pendingUserFiles = ref([]);
  const uploadError = ref("");
  const uploadControllers = new Map();

  function updatePendingUserFile(targetId, patch) {
    pendingUserFiles.value = pendingUserFiles.value.map((item) =>
      item.id === targetId
        ? { ...item, ...(typeof patch === "function" ? patch(item) : patch) }
        : item
    );
  }

  function handleChooseUserFile(fileInputRef) {
    if (loading.value) return;
    fileInputRef.value?.click();
  }

  function uploadPendingUserFile(pendingFile) {
    const controller = new AbortController();
    uploadControllers.set(pendingFile.id, controller);
    demoApi
      .uploadUserFile(
        threadId.value,
        pendingFile.file,
        (loaded, total) => {
          const progress = Math.max(1, Math.min(99, Math.round((loaded / total) * 100)));
          updatePendingUserFile(pendingFile.id, { progress, status: "uploading" });
        },
        controller.signal
      )
      .then((payload) => {
        uploadControllers.delete(pendingFile.id);
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
        });
      })
      .catch((error) => {
        uploadControllers.delete(pendingFile.id);
        if (controller.signal.aborted) return;
        updatePendingUserFile(pendingFile.id, {
          status: "error",
          progress: 0,
          error: error.message || "上传失败。",
        });
      });
  }

  function handlePendingFileChange(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    if (pendingUserFiles.value.length + files.length > MAX_USER_FILE_COUNT) {
      uploadError.value = `最多上传 ${MAX_USER_FILE_COUNT} 个文件。`;
      return;
    }
    const nextFiles = [];
    for (const file of files) {
      const validationError = validatePendingUserFile(file);
      if (validationError) {
        uploadError.value = validationError;
        return;
      }
      nextFiles.push({
        ...createPendingUserFile(file),
        status: "uploading",
        progress: 0,
        error: "",
      });
    }
    uploadError.value = "";
    pendingUserFiles.value = [...pendingUserFiles.value, ...nextFiles].slice(0, MAX_USER_FILE_COUNT);
    for (const pendingFile of nextFiles) {
      uploadPendingUserFile(pendingFile);
    }
  }

  async function handleRemovePendingUserFile(targetId) {
    const target = pendingUserFiles.value.find((item) => item.id === targetId);
    const inflight = uploadControllers.get(targetId);
    if (inflight) {
      inflight.abort();
      uploadControllers.delete(targetId);
    }
    if (target?.path) {
      try {
        await demoApi.deleteUserFile(target.path);
      } catch {}
    }
    pendingUserFiles.value = pendingUserFiles.value.filter((item) => item.id !== targetId);
    uploadError.value = "";
  }

  async function clearPendingUserFiles() {
    const currentFiles = [...pendingUserFiles.value];
    for (const item of currentFiles) {
      const inflight = uploadControllers.get(item.id);
      if (inflight) {
        inflight.abort();
        uploadControllers.delete(item.id);
      }
      if (item.path) {
        try {
          await demoApi.deleteUserFile(item.path);
        } catch {}
      }
    }
    pendingUserFiles.value = [];
    uploadError.value = "";
  }

  function disposeUploads() {
    for (const controller of uploadControllers.values()) {
      controller.abort();
    }
    uploadControllers.clear();
  }

  return {
    pendingUserFiles,
    uploadError,
    handleChooseUserFile,
    handlePendingFileChange,
    handleRemovePendingUserFile,
    clearPendingUserFiles,
    disposeUploads,
  };
}
