import { apiJson } from "./apiClient";

export type CharactersAiImportPreview = {
  schema_version: string;
  title?: string | null;
  summary_md?: string | null;
  ops: Array<{
    op: "upsert" | "dedupe";
    name?: string;
    patch?: {
      role?: string | null;
      profile?: string | null;
      notes?: string | null;
    } | null;
    merge_mode_profile?: string | null;
    merge_mode_notes?: string | null;
    canonical_name?: string | null;
    duplicate_names?: string[];
    reason?: string | null;
  }>;
};

export type WorldbookAiImportPreview = {
  schema_version: string;
  title?: string | null;
  summary_md?: string | null;
  ops: Array<{
    op: "create" | "update" | "merge" | "dedupe";
    match_title?: string | null;
    entry?: {
      title?: string | null;
      content_md?: string | null;
      keywords?: string[];
      aliases?: string[];
      enabled?: boolean | null;
      constant?: boolean | null;
      exclude_recursion?: boolean | null;
      prevent_recursion?: boolean | null;
      char_limit?: number | null;
      priority?: "drop_first" | "optional" | "important" | "must" | null;
    } | null;
    merge_mode?: "append_missing" | "append" | "replace" | null;
    canonical_title?: string | null;
    duplicate_titles?: string[];
    reason?: string | null;
  }>;
};

export type GraphRelationsAiImportPreview = {
  summary_md?: string | null;
  entities: Array<{
    entity_type: string;
    name: string;
    summary_md?: string | null;
    attributes?: Record<string, unknown> | null;
  }>;
  relations: Array<{
    from_entity_name: string;
    to_entity_name: string;
    relation_type: string;
    description_md?: string | null;
    attributes?: Record<string, unknown> | null;
  }>;
};

export type AiImportAnalyzeResult<TPreview> = {
  ok: boolean;
  run_id?: string | null;
  repair_run_id?: string | null;
  warnings?: string[];
  attempts?: Array<Record<string, unknown>>;
  preview: TPreview;
};

export async function analyzeCharactersAiImport(projectId: string, text: string) {
  return apiJson<AiImportAnalyzeResult<CharactersAiImportPreview>>(`/api/projects/${projectId}/characters/ai_import/analyze`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function applyCharactersAiImport(projectId: string, preview: CharactersAiImportPreview) {
  return apiJson<Record<string, unknown>>(`/api/projects/${projectId}/characters/ai_import/apply`, {
    method: "POST",
    body: JSON.stringify({ preview }),
  });
}

export async function analyzeWorldbookAiImport(projectId: string, text: string) {
  return apiJson<AiImportAnalyzeResult<WorldbookAiImportPreview>>(`/api/projects/${projectId}/worldbook_entries/ai_import/analyze`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function applyWorldbookAiImport(projectId: string, preview: WorldbookAiImportPreview) {
  return apiJson<Record<string, unknown>>(`/api/projects/${projectId}/worldbook_entries/ai_import/apply`, {
    method: "POST",
    body: JSON.stringify({ preview }),
  });
}

export async function analyzeGraphRelationsAiImport(projectId: string, text: string) {
  return apiJson<AiImportAnalyzeResult<GraphRelationsAiImportPreview>>(
    `/api/projects/${projectId}/graph/relations/ai_import/analyze`,
    {
      method: "POST",
      body: JSON.stringify({ text }),
    },
  );
}

export async function applyGraphRelationsAiImport(projectId: string, preview: GraphRelationsAiImportPreview) {
  return apiJson<Record<string, unknown>>(`/api/projects/${projectId}/graph/relations/ai_import/apply`, {
    method: "POST",
    body: JSON.stringify({ preview }),
  });
}
