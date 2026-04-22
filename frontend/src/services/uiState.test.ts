import { describe, expect, it } from "vitest";

import { isWizardBarHidden, wizardBarCollapsedStorageKey, wizardBarHiddenStorageKey } from "./uiState";

describe("uiState", () => {
  it("builds a project-scoped storage key for wizard visibility", () => {
    expect(wizardBarHiddenStorageKey("u1", "p1")).toBe("ainovel::wizard_bar_hidden::u1::p1");
    expect(wizardBarCollapsedStorageKey("u1")).toBe("ainovel::wizard_bar_collapsed::u1");
  });

  it("defaults wizard visibility to shown outside the browser", () => {
    expect(isWizardBarHidden("u1", "p1")).toBe(false);
  });
});
