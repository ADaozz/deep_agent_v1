import { watch } from "vue";

import { demoApi } from "../api.js";
import {
  buildUiStateSnapshot,
  rememberLastThreadId,
  rememberTheme,
  writeCachedThreadHistory,
} from "../utils.js";

export function usePersistence({
  threadId,
  uiState,
  history,
}) {
  let uiStateSaveTimer = null;

  watch(
    () => uiState.value.theme,
    (value) => {
      document.documentElement.dataset.theme = value;
      rememberTheme(value);
    },
    { immediate: true }
  );

  watch(threadId, (value) => {
    rememberLastThreadId(value);
  });

  watch(
    history,
    (value) => {
      writeCachedThreadHistory(threadId.value, value);
    },
    { deep: true }
  );

  watch(
    uiState,
    (value) => {
      window.clearTimeout(uiStateSaveTimer);
      uiStateSaveTimer = window.setTimeout(() => {
        demoApi
          .updateThreadState({
            thread_id: threadId.value,
            ui_state: buildUiStateSnapshot(value),
          })
          .catch(() => {});
      }, 250);
    },
    { deep: true }
  );

  function disposePersistence() {
    window.clearTimeout(uiStateSaveTimer);
  }

  return { disposePersistence };
}
