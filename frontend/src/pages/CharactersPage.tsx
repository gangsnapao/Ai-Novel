import { motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { WizardNextBar } from "../components/atelier/WizardNextBar";
import { Drawer } from "../components/ui/Drawer";
import { useConfirm } from "../components/ui/confirm";
import { useToast } from "../components/ui/toast";
import { useAutoSave } from "../hooks/useAutoSave";
import { useProjectData } from "../hooks/useProjectData";
import { useWizardProgress } from "../hooks/useWizardProgress";
import { copyText } from "../lib/copyText";
import { duration, transition } from "../lib/motion";
import { ApiError, apiJson } from "../services/apiClient";
import { analyzeCharactersAiImport, applyCharactersAiImport, type CharactersAiImportPreview } from "../services/aiImportApi";
import { markWizardProjectChanged } from "../services/wizard";
import type { Character } from "../types";

type CharacterForm = {
  name: string;
  role: string;
  profile: string;
  arc_stages_text: string;
  voice_samples_text: string;
  notes: string;
};

function listToMultiline(value: string[] | null | undefined) {
  return (value ?? []).map((item) => String(item ?? "").trim()).filter(Boolean).join("\n");
}

function multilineToList(value: string) {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const line of value.split(/\r?\n/)) {
    const text = line.trim();
    if (!text) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(text);
  }
  return out;
}

export function CharactersPage() {
  const { projectId } = useParams();
  const toast = useToast();
  const confirm = useConfirm();
  const reduceMotion = useReducedMotion();
  const wizard = useWizardProgress(projectId);
  const refreshWizard = wizard.refresh;
  const bumpWizardLocal = wizard.bumpLocal;

  const [loadError, setLoadError] = useState<null | { message: string; code: string; requestId?: string }>(null);

  const charactersQuery = useProjectData<Character[]>(projectId, async (id) => {
    try {
      const res = await apiJson<{ characters: Character[] }>(`/api/projects/${id}/characters`);
      setLoadError(null);
      return res.data.characters;
    } catch (e) {
      if (e instanceof ApiError) {
        setLoadError({ message: e.message, code: e.code, requestId: e.requestId });
      } else {
        setLoadError({ message: "请求失败", code: "UNKNOWN_ERROR" });
      }
      throw e;
    }
  });
  const characters = useMemo(() => charactersQuery.data ?? [], [charactersQuery.data]);
  const loading = charactersQuery.loading;

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Character | null>(null);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const queuedSaveRef = useRef<null | { silent: boolean; close: boolean; snapshot?: CharacterForm }>(null);
  const wizardRefreshTimerRef = useRef<number | null>(null);
  const [baseline, setBaseline] = useState<CharacterForm | null>(null);
  const [form, setForm] = useState<CharacterForm>({
    name: "",
    role: "",
    profile: "",
    arc_stages_text: "",
    voice_samples_text: "",
    notes: "",
  });
  const [searchText, setSearchText] = useState("");
  const [aiImportOpen, setAiImportOpen] = useState(false);
  const [aiImportText, setAiImportText] = useState("");
  const [aiImportLoading, setAiImportLoading] = useState(false);
  const [aiImportApplying, setAiImportApplying] = useState(false);
  const [aiImportPreview, setAiImportPreview] = useState<CharactersAiImportPreview | null>(null);

  const aiImportStats = useMemo(() => {
    const ops = aiImportPreview?.ops ?? [];
    return {
      upserts: ops.filter((item) => item.op === "upsert").length,
      dedupes: ops.filter((item) => item.op === "dedupe").length,
    };
  }, [aiImportPreview]);

  const filteredCharacters = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    if (!q) return characters;
    return characters.filter((c) => {
      const name = String(c.name ?? "").toLowerCase();
      const role = String(c.role ?? "").toLowerCase();
      return name.includes(q) || role.includes(q);
    });
  }, [characters, searchText]);

  const dirty = useMemo(() => {
    if (!baseline) return false;
    return (
      form.name !== baseline.name ||
      form.role !== baseline.role ||
      form.profile !== baseline.profile ||
      form.arc_stages_text !== baseline.arc_stages_text ||
      form.voice_samples_text !== baseline.voice_samples_text ||
      form.notes !== baseline.notes
    );
  }, [baseline, form]);

  const load = charactersQuery.refresh;
  const setCharacters = charactersQuery.setData;

  useEffect(() => {
    return () => {
      if (wizardRefreshTimerRef.current !== null) window.clearTimeout(wizardRefreshTimerRef.current);
    };
  }, []);

  const openNew = () => {
    setEditing(null);
    const next = {
      name: "",
      role: "",
      profile: "",
      arc_stages_text: "",
      voice_samples_text: "",
      notes: "",
    };
    setForm(next);
    setBaseline(next);
    setDrawerOpen(true);
  };

  const openAiImport = () => {
    setAiImportOpen(true);
    setAiImportText("");
    setAiImportPreview(null);
  };

  const openEdit = (c: Character) => {
    setEditing(c);
    const next = {
      name: c.name ?? "",
      role: c.role ?? "",
      profile: c.profile ?? "",
      arc_stages_text: listToMultiline(c.arc_stages),
      voice_samples_text: listToMultiline(c.voice_samples),
      notes: c.notes ?? "",
    };
    setForm(next);
    setBaseline(next);
    setDrawerOpen(true);
  };

  const closeDrawer = async () => {
    if (dirty) {
      const ok = await confirm.confirm({
        title: "放弃未保存修改？",
        description: "关闭后未保存内容会丢失。你可以先点击“保存”再关闭。",
        confirmText: "放弃",
        cancelText: "取消",
        danger: true,
      });
      if (!ok) return;
    }
    setDrawerOpen(false);
  };

  const runAiImportAnalyze = useCallback(async () => {
    if (!projectId) return;
    if (!aiImportText.trim()) {
      toast.toastError("请先粘贴要导入的角色信息");
      return;
    }
    if (aiImportLoading) return;
    setAiImportLoading(true);
    try {
      const res = await analyzeCharactersAiImport(projectId, aiImportText.trim());
      setAiImportPreview(res.data.preview);
      toast.toastSuccess("角色信息已解析");
    } catch (error) {
      const err = error as ApiError;
      toast.toastError(`${err.message} (${err.code})`, err.requestId);
    } finally {
      setAiImportLoading(false);
    }
  }, [aiImportLoading, aiImportText, projectId, toast]);

  const applyAiImport = useCallback(async () => {
    if (!projectId || !aiImportPreview) return;
    if (aiImportApplying) return;
    setAiImportApplying(true);
    try {
      await applyCharactersAiImport(projectId, aiImportPreview);
      await load();
      await refreshWizard();
      markWizardProjectChanged(projectId);
      bumpWizardLocal();
      setAiImportOpen(false);
      setAiImportPreview(null);
      setAiImportText("");
      toast.toastSuccess("角色已导入");
    } catch (error) {
      const err = error as ApiError;
      toast.toastError(`${err.message} (${err.code})`, err.requestId);
    } finally {
      setAiImportApplying(false);
    }
  }, [aiImportApplying, aiImportPreview, bumpWizardLocal, load, projectId, refreshWizard, toast]);

  const saveCharacter = useCallback(
    async (opts?: { silent?: boolean; close?: boolean; snapshot?: CharacterForm }) => {
      if (!projectId) return false;
      const silent = Boolean(opts?.silent);
      const close = Boolean(opts?.close);
      const snapshot = opts?.snapshot ?? form;
      if (!snapshot.name.trim()) return false;

      if (savingRef.current) {
        queuedSaveRef.current = { silent, close, snapshot };
        return false;
      }

      const scheduleWizardRefresh = () => {
        if (wizardRefreshTimerRef.current !== null) window.clearTimeout(wizardRefreshTimerRef.current);
        wizardRefreshTimerRef.current = window.setTimeout(() => void refreshWizard(), 1200);
      };

      savingRef.current = true;
      setSaving(true);
      try {
        const res = !editing
          ? await apiJson<{ character: Character }>(`/api/projects/${projectId}/characters`, {
              method: "POST",
              body: JSON.stringify({
                name: snapshot.name.trim(),
                role: snapshot.role.trim() || null,
                profile: snapshot.profile || null,
                arc_stages: multilineToList(snapshot.arc_stages_text),
                voice_samples: multilineToList(snapshot.voice_samples_text),
                notes: snapshot.notes || null,
              }),
            })
          : await apiJson<{ character: Character }>(`/api/characters/${editing.id}`, {
              method: "PUT",
              body: JSON.stringify({
                name: snapshot.name.trim(),
                role: snapshot.role.trim() || null,
                profile: snapshot.profile || null,
                arc_stages: multilineToList(snapshot.arc_stages_text),
                voice_samples: multilineToList(snapshot.voice_samples_text),
                notes: snapshot.notes || null,
              }),
            });

        const saved = res.data.character;
        setEditing(saved);
        setCharacters((prev) => {
          const list = prev ?? [];
          const idx = list.findIndex((c) => c.id === saved.id);
          if (idx >= 0) return list.map((c) => (c.id === saved.id ? saved : c));
          return [saved, ...list];
        });

        const nextBaseline: CharacterForm = {
          name: saved.name ?? "",
          role: saved.role ?? "",
          profile: saved.profile ?? "",
          arc_stages_text: listToMultiline(saved.arc_stages),
          voice_samples_text: listToMultiline(saved.voice_samples),
          notes: saved.notes ?? "",
        };
        setBaseline(nextBaseline);
        setForm((prev) => {
          if (
            prev.name === snapshot.name &&
            prev.role === snapshot.role &&
            prev.profile === snapshot.profile &&
            prev.arc_stages_text === snapshot.arc_stages_text &&
            prev.voice_samples_text === snapshot.voice_samples_text &&
            prev.notes === snapshot.notes
          ) {
            return nextBaseline;
          }
          return prev;
        });

        markWizardProjectChanged(projectId);
        bumpWizardLocal();
        if (silent) scheduleWizardRefresh();
        else await refreshWizard();
        if (!silent) toast.toastSuccess("已保存");
        if (close) setDrawerOpen(false);
        return true;
      } catch (err) {
        const apiErr = err as ApiError;
        toast.toastError(`${apiErr.message} (${apiErr.code})`, apiErr.requestId);
        return false;
      } finally {
        setSaving(false);
        savingRef.current = false;
        if (queuedSaveRef.current) {
          const queued = queuedSaveRef.current;
          queuedSaveRef.current = null;
          void saveCharacter({ silent: queued.silent, close: queued.close, snapshot: queued.snapshot });
        }
      }
    },
    [bumpWizardLocal, editing, form, projectId, refreshWizard, setCharacters, toast],
  );

  useAutoSave({
    enabled: drawerOpen && Boolean(projectId) && Boolean(baseline),
    dirty,
    delayMs: 900,
    getSnapshot: () => ({ ...form }),
    onSave: async (snapshot) => {
      await saveCharacter({ silent: true, close: false, snapshot });
    },
    deps: [
      editing?.id ?? "",
      form.name,
      form.role,
      form.profile,
      form.arc_stages_text,
      form.voice_samples_text,
      form.notes,
    ],
  });

  return (
    <div className="grid gap-4 pb-[calc(6rem+env(safe-area-inset-bottom))]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <div className="text-sm text-subtext">
            {searchText.trim()
              ? `共 ${filteredCharacters.length}/${characters.length} 位角色`
              : `共 ${characters.length} 位角色`}
          </div>
          <input
            className="input-underline w-full sm:w-64"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="搜索：姓名 / 定位"
            aria-label="角色搜索"
          />
          {searchText.trim() ? (
            <button className="btn btn-ghost px-3 py-2 text-xs" onClick={() => setSearchText("")} type="button">
              清空搜索
            </button>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-secondary" onClick={openAiImport} type="button">
            AI一键导入
          </button>
          <button className="btn btn-primary" onClick={openNew} type="button">
            新增角色
          </button>
        </div>
      </div>

      {loading && charactersQuery.data === null ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={idx} className="panel p-6">
              <div className="skeleton h-5 w-24" />
              <div className="mt-3 grid gap-2">
                <div className="skeleton h-4 w-full" />
                <div className="skeleton h-4 w-5/6" />
                <div className="skeleton h-4 w-2/3" />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {!loading && charactersQuery.data === null && loadError ? (
        <div className="error-card">
          <div className="state-title">加载失败</div>
          <div className="state-desc">{`${loadError.message} (${loadError.code})`}</div>
          {loadError.requestId ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-subtext">
              <span>request_id: {loadError.requestId}</span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => void copyText(loadError.requestId!, { title: "复制 request_id" })}
                type="button"
              >
                复制 request_id
              </button>
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="btn btn-primary" onClick={() => void load()} type="button">
              重试
            </button>
          </div>
        </div>
      ) : null}

      {!loading && !loadError && characters.length === 0 ? (
        <div className="panel p-6">
          <div className="font-content text-xl text-ink">暂无角色</div>
          <div className="mt-2 text-sm text-subtext">
            建议先创建 3-5 个关键角色（主角 / 反派 / 关键 NPC），再进入「大纲」生成章节。
          </div>
          <button className="btn btn-primary mt-4" onClick={openNew} type="button">
            新增角色
          </button>
        </div>
      ) : null}

      {!loading && !loadError && characters.length > 0 && filteredCharacters.length === 0 ? (
        <div className="panel p-6">
          <div className="font-content text-xl text-ink">没有匹配的角色</div>
          <div className="mt-2 text-sm text-subtext">尝试修改搜索关键词，或清空搜索后再查看全部角色。</div>
          <button className="btn btn-secondary mt-4" onClick={() => setSearchText("")} type="button">
            清空搜索
          </button>
        </div>
      ) : null}

      <motion.div
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
        initial="hidden"
        animate="show"
        variants={{
          hidden: {},
          show: { transition: { staggerChildren: reduceMotion ? 0 : duration.stagger } },
        }}
      >
        {filteredCharacters.map((c) => (
          <motion.div
            key={c.id}
            className="panel-interactive ui-focus-ring p-6 text-left"
            initial="hidden"
            animate="show"
            variants={{
              hidden: reduceMotion ? { opacity: 0 } : { opacity: 0, y: 8 },
              show: reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0 },
            }}
            transition={reduceMotion ? transition.reduced : transition.slow}
            whileHover={reduceMotion ? undefined : { y: -2, transition: transition.fast }}
            whileTap={reduceMotion ? undefined : { y: 0, scale: 0.98, transition: transition.fast }}
            onClick={() => openEdit(c)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openEdit(c);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-content text-xl text-ink">{c.name}</div>
                <div className="mt-1 text-xs text-subtext">{c.role ?? "未填写角色定位"}</div>
              </div>
              <button
                className="btn btn-ghost px-3 py-2 text-xs text-danger hover:bg-danger/10"
                onClick={async (e) => {
                  e.stopPropagation();
                  const ok = await confirm.confirm({
                    title: "删除角色？",
                    description: "该角色将从项目中移除。",
                    confirmText: "删除",
                    danger: true,
                  });
                  if (!ok) return;
                  try {
                    await apiJson<Record<string, never>>(`/api/characters/${c.id}`, { method: "DELETE" });
                    if (projectId) markWizardProjectChanged(projectId);
                    bumpWizardLocal();
                    toast.toastSuccess("已删除");
                    await load();
                    await refreshWizard();
                  } catch (err) {
                    const apiErr = err as ApiError;
                    toast.toastError(`${apiErr.message} (${apiErr.code})`, apiErr.requestId);
                  }
                }}
                type="button"
              >
                删除
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-subtext">
              {typeof c.profile_version === "number" && c.profile_version > 0 ? (
                <span>档案 v{c.profile_version}</span>
              ) : null}
              {(c.arc_stages?.length ?? 0) > 0 ? <span>成长轨迹 {c.arc_stages?.length}</span> : null}
              {(c.voice_samples?.length ?? 0) > 0 ? <span>语气样本 {c.voice_samples?.length}</span> : null}
            </div>
            {c.profile ? <div className="mt-3 line-clamp-4 text-sm text-subtext">{c.profile}</div> : null}
          </motion.div>
        ))}
      </motion.div>

      <Drawer
        open={drawerOpen}
        onClose={() => void closeDrawer()}
        panelClassName="h-full w-full max-w-xl border-l border-border bg-canvas p-6 shadow-sm"
        ariaLabel={editing ? "编辑角色" : "新增角色"}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-content text-2xl text-ink">{editing ? "编辑角色" : "新增角色"}</div>
            <div className="mt-1 text-xs text-subtext">{dirty ? "未保存" : "已保存"}</div>
          </div>
          <div className="flex gap-2">
            <button className="btn btn-secondary" onClick={() => void closeDrawer()} type="button">
              关闭
            </button>
            <button
              className="btn btn-primary"
              disabled={saving || !form.name.trim()}
              onClick={() => void saveCharacter({ silent: false, close: true })}
              type="button"
            >
              保存
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-4">
          <label className="grid gap-1">
            <span className="text-xs text-subtext">姓名</span>
            <input
              className="input"
              name="name"
              value={form.name}
              onChange={(e) => setForm((v) => ({ ...v, name: e.target.value }))}
              placeholder="例如：林默"
            />
            <div className="text-[11px] text-subtext">建议使用读者容易记住的短名；后续会用于检索与生成。</div>
          </label>
          <label className="grid gap-1">
            <span className="text-xs text-subtext">角色定位</span>
            <input
              className="input"
              name="role"
              value={form.role}
              onChange={(e) => setForm((v) => ({ ...v, role: e.target.value }))}
              placeholder="例如：主角 / 反派 / 关键 NPC"
            />
            <div className="text-[11px] text-subtext">用于快速筛选；可以写“主角/反派/导师/同伴/路人”等。</div>
          </label>
          <label className="grid gap-1">
            <span className="text-xs text-subtext">人物档案</span>
            <textarea
              className="textarea atelier-content"
              name="profile"
              rows={8}
              value={form.profile}
              onChange={(e) => setForm((v) => ({ ...v, profile: e.target.value }))}
              placeholder="外貌、性格、动机、关系、口癖、成长线…"
            />
            <div className="text-[11px] text-subtext">用于生成时的角色一致性；可按条目写，更易复用。</div>
          </label>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-1">
              <span className="text-xs text-subtext">成长轨迹</span>
              <textarea
                className="textarea atelier-content"
                name="arc_stages_text"
                rows={6}
                value={form.arc_stages_text}
                onChange={(e) => setForm((v) => ({ ...v, arc_stages_text: e.target.value }))}
                placeholder={"每行一条，例如：\n第一卷：逃亡求生\n第二卷：学会掌权"}
              />
              <div className="text-[11px] text-subtext">按时间顺序写，每行一个阶段，后续可直接喂给角色生成与回顾。</div>
            </label>
            <label className="grid gap-1">
              <span className="text-xs text-subtext">语气样本</span>
              <textarea
                className="textarea atelier-content"
                name="voice_samples_text"
                rows={6}
                value={form.voice_samples_text}
                onChange={(e) => setForm((v) => ({ ...v, voice_samples_text: e.target.value }))}
                placeholder={"每行一条，例如：\n“别急，先让我想想。”\n“你们退后，这里交给我。”"}
              />
              <div className="text-[11px] text-subtext">记录常用口吻、节奏和措辞，后续更容易保持人物说话一致。</div>
            </label>
          </div>
          {editing ? (
            <div className="rounded-atelier border border-border bg-surface p-3 text-xs text-subtext">
              <div>当前档案版本：v{editing.profile_version ?? 0}</div>
              {(editing.profile_history?.length ?? 0) > 0 ? (
                <details className="mt-2">
                  <summary className="cursor-pointer select-none text-ink">查看历史档案</summary>
                  <div className="mt-2 grid gap-2">
                    {(editing.profile_history ?? []).slice().reverse().map((item, index) => (
                      <div key={`${item.version ?? "v"}-${index}`} className="rounded-atelier border border-border/70 bg-canvas p-2">
                        <div className="text-[11px] text-subtext">
                          v{item.version ?? "?"} {item.captured_at ? `· ${item.captured_at}` : ""}
                        </div>
                        <div className="mt-1 whitespace-pre-wrap text-xs text-ink">{item.profile}</div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : (
                <div className="mt-1">尚无历史档案，后续每次修改人物档案都会自动留痕。</div>
              )}
            </div>
          ) : null}
          <label className="grid gap-1">
            <span className="text-xs text-subtext">备注</span>
            <textarea
              className="textarea atelier-content"
              name="notes"
              rows={6}
              value={form.notes}
              onChange={(e) => setForm((v) => ({ ...v, notes: e.target.value }))}
              placeholder="出场章节、禁忌、时间线、待补信息…"
            />
            <div className="text-[11px] text-subtext">记录未定稿/待补充信息，避免混进人物档案造成误导。</div>
          </label>
        </div>
      </Drawer>

      <Drawer
        open={aiImportOpen}
        onClose={() => {
          if (aiImportLoading || aiImportApplying) return;
          setAiImportOpen(false);
        }}
        panelClassName="h-full w-full max-w-2xl border-l border-border bg-canvas p-6 shadow-sm"
        ariaLabel="角色 AI 一键导入"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-content text-2xl text-ink">角色 AI 一键导入</div>
            <div className="mt-1 text-xs text-subtext">粘贴人物设定、角色表或剧情片段，AI 会整理成角色卡导入现有列表。</div>
          </div>
          <div className="flex gap-2">
            <button
              className="btn btn-secondary"
              disabled={aiImportLoading || aiImportApplying}
              onClick={() => setAiImportOpen(false)}
              type="button"
            >
              关闭
            </button>
            <button
              className="btn btn-primary"
              disabled={!aiImportPreview || aiImportLoading || aiImportApplying}
              onClick={() => void applyAiImport()}
              type="button"
            >
              {aiImportApplying ? "导入中..." : "导入到角色卡"}
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-4">
          <label className="grid gap-1">
            <span className="text-xs text-subtext">粘贴内容</span>
            <textarea
              className="textarea atelier-content"
              rows={12}
              value={aiImportText}
              onChange={(e) => setAiImportText(e.target.value)}
              placeholder="例如：角色名单、人物设定、人物小传、章节片段等"
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              className="btn btn-secondary"
              disabled={!aiImportText.trim() || aiImportLoading || aiImportApplying}
              onClick={() => void runAiImportAnalyze()}
              type="button"
            >
              {aiImportLoading ? "解析中..." : "开始解析"}
            </button>
            {aiImportPreview ? (
              <div className="text-xs text-subtext">
                识别到 {aiImportStats.upserts} 条角色更新，{aiImportStats.dedupes} 条去重建议
              </div>
            ) : null}
          </div>

          {aiImportPreview?.summary_md ? (
            <div className="rounded-atelier border border-border bg-surface p-3 text-sm text-subtext">
              {aiImportPreview.summary_md}
            </div>
          ) : null}

          {aiImportPreview ? (
            <div className="grid gap-3">
              {(aiImportPreview.ops ?? []).length === 0 ? (
                <div className="rounded-atelier border border-border bg-surface p-3 text-sm text-subtext">
                  AI 没有识别到可导入的角色信息。
                </div>
              ) : (
                (aiImportPreview.ops ?? []).map((op, idx) => (
                  <div key={`${op.op}-${idx}`} className="rounded-atelier border border-border bg-surface p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-subtext">
                      <span className="rounded border border-border px-2 py-0.5 text-ink">{op.op}</span>
                      {op.op === "upsert" ? <span>{op.name || "未命名角色"}</span> : null}
                      {op.op === "dedupe" ? <span>{op.canonical_name || "未指定主名称"}</span> : null}
                    </div>
                    {op.op === "upsert" ? (
                      <div className="mt-2 grid gap-2 text-sm text-subtext">
                        {op.patch?.role ? <div>定位：{op.patch.role}</div> : null}
                        {op.patch?.profile ? <div className="line-clamp-4">{op.patch.profile}</div> : null}
                        {op.patch?.notes ? <div className="line-clamp-3 text-xs">{op.patch.notes}</div> : null}
                      </div>
                    ) : null}
                    {op.op === "dedupe" && op.duplicate_names?.length ? (
                      <div className="mt-2 text-sm text-subtext">合并重复名：{op.duplicate_names.join("、")}</div>
                    ) : null}
                    {op.reason ? <div className="mt-2 text-xs text-subtext">原因：{op.reason}</div> : null}
                  </div>
                ))
              )}
            </div>
          ) : null}
        </div>
      </Drawer>

      <WizardNextBar
        projectId={projectId}
        currentStep="characters"
        progress={wizard.progress}
        loading={wizard.loading}
        primaryAction={
          wizard.progress.nextStep?.key === "characters" ? { label: "本页：新增角色", onClick: openNew } : undefined
        }
      />
    </div>
  );
}
