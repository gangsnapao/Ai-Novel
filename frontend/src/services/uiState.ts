import { storageKey } from "./storageKeys";

export const WIZARD_BAR_VISIBILITY_CHANGED_EVENT = "ainovel:wizard_bar_visibility_changed";

export type WizardBarVisibilityChangedDetail = {
  userId: string;
  projectId: string;
  hidden: boolean;
};

export function sidebarCollapsedStorageKey(userId: string): string {
  return storageKey("sidebar_collapsed", userId);
}

export function advancedDebugVisibleStorageKey(userId: string): string {
  return storageKey("advanced_debug", "visible", userId);
}

export function advancedDebugCollapsedStorageKey(userId: string): string {
  return storageKey("advanced_debug", "collapsed", userId);
}

export function wizardBarCollapsedStorageKey(userId: string): string {
  return storageKey("wizard_bar_collapsed", userId);
}

export function wizardBarHiddenStorageKey(userId: string, projectId: string): string {
  return storageKey("wizard_bar_hidden", userId, projectId);
}

export function isWizardBarHidden(userId: string, projectId: string): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(wizardBarHiddenStorageKey(userId, projectId)) === "1";
}

export function setWizardBarHidden(userId: string, projectId: string, hidden: boolean): void {
  if (typeof window === "undefined") return;
  const key = wizardBarHiddenStorageKey(userId, projectId);
  if (hidden) window.localStorage.setItem(key, "1");
  else window.localStorage.removeItem(key);
  window.dispatchEvent(
    new CustomEvent<WizardBarVisibilityChangedDetail>(WIZARD_BAR_VISIBILITY_CHANGED_EVENT, {
      detail: { userId, projectId, hidden },
    }),
  );
}

export function onWizardBarVisibilityChanged(
  handler: (detail: WizardBarVisibilityChangedDetail) => void,
): () => void {
  if (typeof window === "undefined") return () => {};
  const listener = (event: Event) => {
    const custom = event as CustomEvent<WizardBarVisibilityChangedDetail>;
    if (!custom.detail?.userId || !custom.detail?.projectId) return;
    handler(custom.detail);
  };
  window.addEventListener(WIZARD_BAR_VISIBILITY_CHANGED_EVENT, listener);
  return () => window.removeEventListener(WIZARD_BAR_VISIBILITY_CHANGED_EVENT, listener);
}

export function writingMemoryInjectionEnabledStorageKey(userId: string, projectId: string): string {
  return storageKey("writing", "memory_injection_enabled", userId, projectId);
}
