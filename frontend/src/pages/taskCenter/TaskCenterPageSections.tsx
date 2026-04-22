import { Link } from "react-router-dom";

import { DebugDetails } from "../../components/atelier/DebugPageShell";
import { Drawer } from "../../components/ui/Drawer";
import { humanizeChangeSetStatus, humanizeTaskStatus } from "../../lib/humanize";
import { UI_COPY } from "../../lib/uiCopy";
import type { ProjectTaskRuntime } from "../../services/projectTaskRuntime";

import { extractHowToFix, safeJsonStringify } from "./helpers";
import { ProjectTaskRuntimePanel } from "./ProjectTaskRuntimePanel";
import { StatusBadge } from "./StatusBadge";
import { TASK_CENTER_COPY } from "./taskCenterCopy";
import {
  formatMetricsLatency,
  formatMetricsQueueRun,
  formatMetricsRate,
  formatTaskCenterErrorText,
  type HealthData,
  type MemoryChangeSetSummary,
  type MemoryTaskSummary,
  type ProjectTaskSummary,
  type TaskCenterMetricsBucket,
  type TaskCenterMetricsOverview,
  type TaskCenterSelectedItem,
  type TaskUserVisibleError,
} from "./taskCenterModels";

function RequestIdRow(props: {
  requestId: string;
  buttonLabel: string;
  onCopy: (requestId: string) => void;
  className?: string;
}) {
  return (
    <div className={props.className ?? "mt-1 flex items-center gap-2 text-[11px] text-subtext"}>
      <span className="truncate">
        {UI_COPY.common.requestIdLabel}: <span className="font-mono">{props.requestId}</span>
      </span>
      <button
        className="btn btn-ghost px-2 py-1 text-[11px]"
        onClick={() => props.onCopy(props.requestId)}
        type="button"
      >
        {props.buttonLabel}
      </button>
    </div>
  );
}

function UserVisibleErrorsBlock(props: { errors?: TaskUserVisibleError[] | null }) {
  const items = (props.errors ?? []).filter((item) => item && (item.title || item.message || item.detail));
  if (items.length === 0) return null;

  return (
    <div className="grid gap-2">
      {items.map((item, index) => (
        <div key={`${item.code ?? "err"}-${index}`} className="rounded-atelier border border-danger/30 bg-danger/5 p-2">
          <div className="text-xs font-medium text-danger">{item.title || item.code || "任务失败"}</div>
          {item.message ? <div className="mt-1 text-xs text-ink">{item.message}</div> : null}
          {item.detail ? <div className="mt-1 whitespace-pre-wrap text-[11px] text-subtext">{item.detail}</div> : null}
          {item.request_id ? (
            <div className="mt-1 text-[11px] text-subtext">
              request_id: <span className="font-mono">{item.request_id}</span>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export type TaskCenterHealthBannerProps = {
  health: { data: HealthData; requestId: string } | null;
  onCopyRequestId: (requestId: string) => void;
};

export function TaskCenterHealthBanner(props: TaskCenterHealthBannerProps) {
  if (!props.health?.data.queue_backend) return null;

  return (
    <section
      className="rounded-atelier border border-border bg-surface p-3 text-[11px] text-subtext"
      aria-label={TASK_CENTER_COPY.queueStatusAria}
    >
      <div>
        {TASK_CENTER_COPY.queueBackendLabel}：
        <span className="font-mono text-ink">{props.health.data.queue_backend}</span>
        {props.health.data.effective_backend ? (
          <>
            {" "}
            | {TASK_CENTER_COPY.effectiveBackendLabel}：{" "}
            <span className="font-mono text-ink">{props.health.data.effective_backend}</span>
          </>
        ) : null}
        {props.health.data.queue_backend === "rq" ? (
          <>
            {" "}
            | {TASK_CENTER_COPY.redisOkLabel}：
            <span className="font-mono text-ink">{String(props.health.data.redis_ok ?? "-")}</span>
            {props.health.data.rq_queue_name ? (
              <>
                {" "}
                | {TASK_CENTER_COPY.queueNameLabel}：
                <span className="font-mono text-ink">{props.health.data.rq_queue_name}</span>
              </>
            ) : null}
          </>
        ) : null}
      </div>
      {props.health.data.effective_backend === "inline" ? (
        <div className="mt-1 text-warning">{TASK_CENTER_COPY.queueInlineWarning}</div>
      ) : null}
      {props.health.data.worker_hint ? <div className="mt-1">{props.health.data.worker_hint}</div> : null}
      {props.health.requestId ? (
        <RequestIdRow
          requestId={props.health.requestId}
          buttonLabel={TASK_CENTER_COPY.queueHealthCopyButton}
          onCopy={props.onCopyRequestId}
          className="mt-1 flex items-center gap-2"
        />
      ) : null}
    </section>
  );
}

export type TaskCenterHelpSectionProps = {
  projectId?: string;
};

export function TaskCenterHelpSection(props: TaskCenterHelpSectionProps) {
  return (
    <DebugDetails title={UI_COPY.help.title}>
      <div className="grid gap-2 text-xs text-subtext">
        <div>{UI_COPY.taskCenter.usageHint}</div>
        {props.projectId ? (
          <div>
            {TASK_CENTER_COPY.usageLinksPrefix}{" "}
            <Link className="underline" to={`/projects/${props.projectId}/structured-memory`}>
              {TASK_CENTER_COPY.helpStructuredMemory}
            </Link>{" "}
            与{" "}
            <Link className="underline" to={`/projects/${props.projectId}/writing`}>
              {TASK_CENTER_COPY.helpWriting}
            </Link>{" "}
            {TASK_CENTER_COPY.helpUsageSuffix}
          </div>
        ) : null}
        <div className="text-warning">{UI_COPY.taskCenter.riskHint}</div>
      </div>
    </DebugDetails>
  );
}

type MetricsCardProps = {
  title: string;
  bucket: TaskCenterMetricsBucket;
  latencyLabel: string;
};

function MetricsCard(props: MetricsCardProps) {
  const topKinds = (props.bucket.kind_breakdown ?? []).slice(0, 4);

  return (
    <div className="surface p-3">
      <div className="text-sm text-ink">{props.title}</div>
      <div className="mt-3 grid gap-2 text-xs text-subtext sm:grid-cols-2">
        <div>
          <div>{TASK_CENTER_COPY.metricsMetricTotal}</div>
          <div className="mt-1 text-sm text-ink">{props.bucket.total}</div>
        </div>
        <div>
          <div>{TASK_CENTER_COPY.metricsMetricQueue}</div>
          <div className="mt-1 text-sm text-ink">{formatMetricsQueueRun(props.bucket)}</div>
        </div>
        <div>
          <div>{TASK_CENTER_COPY.metricsMetricSuccess}</div>
          <div className="mt-1 text-sm text-ink">{formatMetricsRate(props.bucket.success_rate)}</div>
        </div>
        <div>
          <div>{props.latencyLabel}</div>
          <div className="mt-1 text-sm text-ink">{formatMetricsLatency(props.bucket)}</div>
        </div>
      </div>
      {topKinds.length > 0 ? (
        <div className="mt-3 border-t border-border pt-3">
          <div className="text-[11px] text-subtext">{TASK_CENTER_COPY.metricsMetricKinds}</div>
          <div className="mt-2 grid gap-2">
            {topKinds.map((item) => (
              <div key={item.kind} className="flex items-center justify-between gap-3 text-xs">
                <div className="min-w-0 truncate text-ink">{item.kind}</div>
                <div className="shrink-0 text-subtext">
                  {item.total} total | {item.failed} failed | {item.running} running
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export type TaskCenterMetricsSectionProps = {
  loading: boolean;
  metrics: { data: TaskCenterMetricsOverview; requestId: string } | null;
  windowHours: number;
  onWindowHoursChange: (value: number) => void;
  onCopyRequestId: (requestId: string) => void;
};

export function TaskCenterMetricsSection(props: TaskCenterMetricsSectionProps) {
  return (
    <section className="panel p-4" aria-label={TASK_CENTER_COPY.metricsSectionAria}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm text-ink">{TASK_CENTER_COPY.metricsTitle}</div>
          <div className="mt-1 text-xs text-subtext">{TASK_CENTER_COPY.metricsHint}</div>
          {props.metrics?.data.as_of ? (
            <div className="mt-1 text-[11px] text-subtext">
              {TASK_CENTER_COPY.metricsUpdatedPrefix} {props.metrics.data.as_of}
            </div>
          ) : null}
          {props.metrics?.requestId ? (
            <RequestIdRow
              requestId={props.metrics.requestId}
              buttonLabel={TASK_CENTER_COPY.metricsRequestIdButton}
              onCopy={props.onCopyRequestId}
            />
          ) : null}
        </div>
        <label className="grid gap-1">
          <span className="text-[11px] text-subtext">{TASK_CENTER_COPY.metricsWindowLabel}</span>
          <select
            className="select"
            aria-label="taskcenter_metrics_window"
            value={String(props.windowHours)}
            onChange={(event) => props.onWindowHoursChange(Number(event.target.value) || 24)}
          >
            <option value="24">{TASK_CENTER_COPY.metricsWindowOptions["24"]}</option>
            <option value="72">{TASK_CENTER_COPY.metricsWindowOptions["72"]}</option>
            <option value="168">{TASK_CENTER_COPY.metricsWindowOptions["168"]}</option>
          </select>
        </label>
      </div>

      {props.loading ? <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.loading}</div> : null}

      {props.metrics ? (
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          <MetricsCard
            title={TASK_CENTER_COPY.metricsCardProjectTasks}
            bucket={props.metrics.data.project_tasks}
            latencyLabel={TASK_CENTER_COPY.metricsMetricLatency}
          />
          <MetricsCard
            title={TASK_CENTER_COPY.metricsCardMemoryTasks}
            bucket={props.metrics.data.memory_tasks}
            latencyLabel={TASK_CENTER_COPY.metricsMetricLatency}
          />
          <MetricsCard
            title={TASK_CENTER_COPY.metricsCardImports}
            bucket={props.metrics.data.imports}
            latencyLabel={TASK_CENTER_COPY.metricsMetricRunOnly}
          />
        </div>
      ) : null}
    </section>
  );
}

type ChangeSetSummaryView = {
  all: number;
  proposed: number;
  applied: number;
  rolled_back: number;
  failed: number;
};

export type TaskCenterChangeSetsSectionProps = {
  loading: boolean;
  items: MemoryChangeSetSummary[];
  summary: ChangeSetSummaryView;
  status: string;
  onStatusChange: (value: string) => void;
  onSelect: (item: MemoryChangeSetSummary) => void;
  onCopyRequestId: (requestId: string) => void;
};

export function TaskCenterChangeSetsSection(props: TaskCenterChangeSetsSectionProps) {
  return (
    <section className="panel p-4" aria-label={TASK_CENTER_COPY.changeSetsSectionAria}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm text-ink">{TASK_CENTER_COPY.changeSetsTitle}</div>
          <div className="mt-1 text-xs text-subtext">{TASK_CENTER_COPY.changeSetsHint}</div>
          <div className="mt-1 text-[11px] text-subtext">{TASK_CENTER_COPY.changeSetsStatusHint}</div>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-subtext">
            <span>
              {TASK_CENTER_COPY.changeSetsCounts.all} {props.summary.all}
            </span>
            <span>
              {TASK_CENTER_COPY.changeSetsCounts.proposed} {props.summary.proposed}
            </span>
            <span>
              {TASK_CENTER_COPY.changeSetsCounts.applied} {props.summary.applied}
            </span>
            <span>
              {TASK_CENTER_COPY.changeSetsCounts.rolledBack} {props.summary.rolled_back}
            </span>
            <span>
              {TASK_CENTER_COPY.changeSetsCounts.failed} {props.summary.failed}
            </span>
          </div>
        </div>
        <label className="grid gap-1">
          <span className="text-[11px] text-subtext">{TASK_CENTER_COPY.changeSetsStatusLabel}</span>
          <select
            className="select"
            aria-label="taskcenter_changeset_status"
            value={props.status}
            onChange={(event) => props.onStatusChange(event.target.value)}
          >
            <option value="all">{TASK_CENTER_COPY.allOption}</option>
            <option value="proposed">{humanizeChangeSetStatus("proposed")}</option>
            <option value="applied">{humanizeChangeSetStatus("applied")}</option>
            <option value="rolled_back">{humanizeChangeSetStatus("rolled_back")}</option>
            <option value="failed">{humanizeChangeSetStatus("failed")}</option>
          </select>
        </label>
      </div>

      {props.loading ? <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.loading}</div> : null}
      {!props.loading && props.items.length === 0 ? (
        <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.changeSetsEmpty}</div>
      ) : null}

      <div className="mt-3 grid gap-2">
        {props.items.map((item) => (
          <button
            key={item.id}
            className="surface surface-interactive w-full p-3 text-left"
            onClick={() => props.onSelect(item)}
            type="button"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm text-ink">{item.title || item.summary_md || item.id}</div>
                <div className="mt-1 truncate text-xs text-subtext">
                  章节 ID：{item.chapter_id || "-"} | 更新时间：{item.updated_at || item.created_at || "-"}
                </div>
                {item.request_id ? (
                  <RequestIdRow
                    requestId={item.request_id}
                    buttonLabel={TASK_CENTER_COPY.requestIdCopyButton}
                    onCopy={props.onCopyRequestId}
                  />
                ) : null}
              </div>
              <StatusBadge status={item.status} kind="change_set" />
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

type TaskSummaryView = {
  all: number;
  queued: number;
  running: number;
  done: number;
  failed: number;
};

export type TaskCenterTasksSectionProps = {
  loading: boolean;
  items: MemoryTaskSummary[];
  summary: TaskSummaryView;
  status: string;
  onStatusChange: (value: string) => void;
  onToggleFailedOnly: () => void;
  onSelect: (item: MemoryTaskSummary) => void;
  onCopyRequestId: (requestId: string) => void;
};

export function TaskCenterTasksSection(props: TaskCenterTasksSectionProps) {
  return (
    <section className="panel p-4" aria-label={TASK_CENTER_COPY.tasksSectionAria}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm text-ink">{TASK_CENTER_COPY.tasksTitle}</div>
          <div className="mt-1 text-xs text-subtext">
            {TASK_CENTER_COPY.tasksHintPrefix}
            {UI_COPY.common.requestIdLabel}
          </div>
          <div className="mt-1 text-[11px] text-subtext">{TASK_CENTER_COPY.tasksStatusHint}</div>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-subtext">
            <span>
              {TASK_CENTER_COPY.countLabels.all} {props.summary.all}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.queued} {props.summary.queued}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.running} {props.summary.running}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.done} {props.summary.done}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.failed} {props.summary.failed}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <button
            className="btn btn-secondary"
            aria-label="失败任务筛选 (taskcenter_failed_only)"
            onClick={props.onToggleFailedOnly}
            type="button"
          >
            {TASK_CENTER_COPY.tasksFailedOnly}
          </button>
          <label className="grid gap-1">
            <span className="text-[11px] text-subtext">{TASK_CENTER_COPY.changeSetsStatusLabel}</span>
            <select
              className="select"
              aria-label="taskcenter_task_status"
              value={props.status}
              onChange={(event) => props.onStatusChange(event.target.value)}
            >
              <option value="all">{TASK_CENTER_COPY.allOption}</option>
              <option value="queued">{humanizeTaskStatus("queued")}</option>
              <option value="running">{humanizeTaskStatus("running")}</option>
              <option value="done">{humanizeTaskStatus("done")}</option>
              <option value="failed">{humanizeTaskStatus("failed")}</option>
            </select>
          </label>
        </div>
      </div>

      {props.loading ? <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.loading}</div> : null}
      {!props.loading && props.items.length === 0 ? (
        <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.tasksEmpty}</div>
      ) : null}

      <div className="mt-3 grid gap-2">
        {props.items.map((item) => (
          <button
            key={item.id}
            className="surface surface-interactive w-full p-3 text-left"
            onClick={() => props.onSelect(item)}
            type="button"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm text-ink">
                  {item.kind} <span className="text-subtext">({item.id})</span>
                </div>
                <div className="mt-1 truncate text-xs text-subtext">变更集 ID：{item.change_set_id}</div>
                {item.request_id ? (
                  <RequestIdRow
                    requestId={item.request_id}
                    buttonLabel={TASK_CENTER_COPY.requestIdCopyButton}
                    onCopy={props.onCopyRequestId}
                  />
                ) : null}
                {item.status === "failed" ? (
                  <div className="mt-1 grid gap-2">
                    <div className="truncate text-xs text-danger">
                      {formatTaskCenterErrorText(item.error_type, item.error_message)}
                    </div>
                    <UserVisibleErrorsBlock errors={item.user_visible_errors} />
                  </div>
                ) : null}
              </div>
              <StatusBadge status={item.status} kind="task" />
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

export type TaskCenterProjectTasksSectionProps = {
  loading: boolean;
  items: ProjectTaskSummary[];
  summary: TaskSummaryView;
  status: string;
  liveStatusLabel: string;
  onStatusChange: (value: string) => void;
  onToggleFailedOnly: () => void;
  onSelect: (item: ProjectTaskSummary) => void;
  onRetry: (taskId: string) => void;
  onCancel: (taskId: string) => void;
};

export function TaskCenterProjectTasksSection(props: TaskCenterProjectTasksSectionProps) {
  return (
    <section className="panel p-4 lg:col-span-2" aria-label={TASK_CENTER_COPY.projectTasksSectionAria}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm text-ink">{TASK_CENTER_COPY.projectTasksTitle}</div>
          <div className="mt-1 text-xs text-subtext">{TASK_CENTER_COPY.projectTasksHint}</div>
          <div className="mt-1 text-[11px] text-subtext">{TASK_CENTER_COPY.projectTasksStatusHint}</div>
          <div className="mt-1 text-[11px] text-subtext" aria-label="taskcenter_projecttask_live_status">
            {TASK_CENTER_COPY.projectTasksLiveStatusPrefix}
            {props.liveStatusLabel}
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-subtext">
            <span>
              {TASK_CENTER_COPY.countLabels.all} {props.summary.all}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.queued} {props.summary.queued}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.running} {props.summary.running}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.done} {props.summary.done}
            </span>
            <span>
              {TASK_CENTER_COPY.countLabels.failed} {props.summary.failed}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <button
            className="btn btn-secondary"
            aria-label="项目任务仅看失败 (taskcenter_projecttask_failed_only)"
            onClick={props.onToggleFailedOnly}
            type="button"
          >
            {TASK_CENTER_COPY.projectTasksFailedOnly}
          </button>
          <label className="grid gap-1">
            <span className="text-[11px] text-subtext">{TASK_CENTER_COPY.changeSetsStatusLabel}</span>
            <select
              className="select"
              aria-label="taskcenter_projecttask_status"
              value={props.status}
              onChange={(event) => props.onStatusChange(event.target.value)}
            >
              <option value="all">{TASK_CENTER_COPY.allOption}</option>
              <option value="queued">{humanizeTaskStatus("queued")}</option>
              <option value="running">{humanizeTaskStatus("running")}</option>
              <option value="done">{humanizeTaskStatus("done")}</option>
              <option value="failed">{humanizeTaskStatus("failed")}</option>
            </select>
          </label>
        </div>
      </div>

      {props.loading ? <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.loading}</div> : null}
      {!props.loading && props.items.length === 0 ? (
        <div className="mt-3 text-sm text-subtext">{TASK_CENTER_COPY.projectTasksEmpty}</div>
      ) : null}

      <div className="mt-3 grid gap-2">
        {props.items.map((item) => (
          <button
            key={item.id}
            className="surface surface-interactive w-full p-3 text-left"
            onClick={() => props.onSelect(item)}
            type="button"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm text-ink">
                  {item.kind} <span className="text-subtext">({item.id})</span>
                </div>
                {item.idempotency_key ? (
                  <div className="mt-1 truncate text-xs text-subtext">
                    {TASK_CENTER_COPY.projectTasksIdempotencyPrefix}
                    {item.idempotency_key}
                  </div>
                ) : null}
                {item.status === "failed" ? (
                  <div className="mt-1 truncate text-xs text-danger">
                    {formatTaskCenterErrorText(item.error_type, item.error_message)}
                  </div>
                ) : null}
              </div>

              <div className="flex items-center gap-2">
                {item.status === "failed" ? (
                  <button
                    className="btn btn-secondary btn-sm"
                    aria-label="项目任务重试 (taskcenter_projecttask_retry)"
                    onClick={(event) => {
                      event.stopPropagation();
                      props.onRetry(item.id);
                    }}
                    type="button"
                  >
                    {TASK_CENTER_COPY.projectTasksRetry}
                  </button>
                ) : null}
                {item.status === "queued" ? (
                  <button
                    className="btn btn-secondary btn-sm"
                    aria-label="取消项目任务 (taskcenter_projecttask_cancel)"
                    onClick={(event) => {
                      event.stopPropagation();
                      props.onCancel(item.id);
                    }}
                    type="button"
                  >
                    {TASK_CENTER_COPY.projectTasksCancel}
                  </button>
                ) : null}
                <StatusBadge status={item.status} kind="task" />
              </div>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

export type TaskCenterDetailDrawerProps = {
  selected: TaskCenterSelectedItem;
  detailTitle: string;
  detailHeading: string;
  projectTaskDetailLoading: boolean;
  selectedProjectTaskRuntime: ProjectTaskRuntime | null;
  projectTaskRuntimeLoading: boolean;
  projectTaskBatchActionLoading: boolean;
  selectedProjectTaskChangeSetId: string | null;
  liveChangeSetStatus: string | null;
  selectedProjectTaskRunId: string | null;
  changeSetActionLoading: boolean;
  onClose: () => void;
  onCopyDebugInfo: () => void;
  onCopyRawJson: () => void;
  onCopyRequestId: (requestId: string) => void;
  onCopyRunId: (runId: string) => void;
  onRefreshProjectTaskDetail: () => void;
  onRetryProjectTask: (taskId: string) => void;
  onCancelProjectTask: (taskId: string) => void;
  onRefreshProjectTaskRuntime: () => void;
  onPauseBatch: () => void;
  onResumeBatch: () => void;
  onRetryFailedBatch: () => void;
  onSkipFailedBatch: () => void;
  onCancelBatch: () => void;
  onApplyChangeSet: (changeSetId: string) => void;
  onRollbackChangeSet: (changeSetId: string) => void;
};

export function TaskCenterDetailDrawer(props: TaskCenterDetailDrawerProps) {
  return (
    <Drawer
      open={Boolean(props.selected)}
      onClose={props.onClose}
      ariaLabel={props.detailTitle}
      panelClassName="h-full w-full max-w-2xl border-l border-border bg-canvas p-6 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-content text-2xl text-ink">{props.detailHeading || props.detailTitle}</div>
          {props.selected ? (
            <div className="mt-1 text-xs text-subtext">
              ID：{props.selected.item.id}{" "}
              {props.selected.kind === "task"
                ? `| ${UI_COPY.common.requestIdLabel}: ${props.selected.item.request_id ?? "-"}`
                : props.selected.kind === "project_task"
                  ? `| 幂等键：${props.selected.item.idempotency_key ?? "-"}`
                  : ""}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn btn-secondary" onClick={props.onCopyDebugInfo} aria-label="复制排障信息" type="button">
            {TASK_CENTER_COPY.detailCopyDebug}
          </button>
          <button className="btn btn-secondary" onClick={props.onClose} type="button">
            {TASK_CENTER_COPY.detailClose}
          </button>
        </div>
      </div>

      {props.selected?.kind === "change_set" ? (
        <div className="mt-5 grid gap-3">
          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="changeset_overview">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailOverview}</div>
            <div className="mt-2 grid gap-1 text-xs text-subtext">
              <div>
                章节 ID：<span className="font-mono text-ink">{props.selected.item.chapter_id || "-"}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span>状态：</span>
                <StatusBadge status={props.selected.item.status} kind="change_set" />
              </div>
              <div>
                idempotency_key：
                <span className="font-mono text-ink">{props.selected.item.idempotency_key || "-"}</span>
              </div>
              {props.selected.item.request_id ? (
                <RequestIdRow
                  requestId={props.selected.item.request_id}
                  buttonLabel={TASK_CENTER_COPY.requestIdCopyButton}
                  onCopy={props.onCopyRequestId}
                />
              ) : null}
              <div>
                created_at：<span className="font-mono text-ink">{props.selected.item.created_at || "-"}</span>
              </div>
              <div>
                updated_at：<span className="font-mono text-ink">{props.selected.item.updated_at || "-"}</span>
              </div>
            </div>
          </section>
          <details className="rounded-atelier border border-border bg-surface p-3">
            <summary className="cursor-pointer select-none text-sm text-ink">{TASK_CENTER_COPY.detailRawJson}</summary>
            <div className="mt-3 flex items-center justify-end">
              <button className="btn btn-secondary btn-sm" onClick={props.onCopyRawJson} type="button">
                {TASK_CENTER_COPY.detailCopyDebug}
              </button>
            </div>
            <pre className="mt-2 whitespace-pre-wrap break-words rounded-atelier border border-border bg-canvas p-3 text-xs text-ink">
              {safeJsonStringify(props.selected.item)}
            </pre>
          </details>
        </div>
      ) : null}

      {props.selected?.kind === "task" ? (
        <div className="mt-5 grid gap-3">
          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="memorytask_overview">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailOverview}</div>
            <div className="mt-2 grid gap-1 text-xs text-subtext">
              <div>
                Kind：<span className="font-mono text-ink">{props.selected.item.kind}</span>
              </div>
              <div>
                change_set_id：<span className="font-mono text-ink">{props.selected.item.change_set_id}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span>状态：</span>
                <StatusBadge status={props.selected.item.status} kind="task" />
              </div>
              <div>
                created_at：
                <span className="font-mono text-ink">
                  {String(
                    (props.selected.item.timings as Record<string, unknown> | null | undefined)?.created_at ?? "-",
                  )}
                </span>
              </div>
              <div>
                started_at：
                <span className="font-mono text-ink">
                  {String(
                    (props.selected.item.timings as Record<string, unknown> | null | undefined)?.started_at ?? "-",
                  )}
                </span>
              </div>
              <div>
                finished_at：
                <span className="font-mono text-ink">
                  {String(
                    (props.selected.item.timings as Record<string, unknown> | null | undefined)?.finished_at ?? "-",
                  )}
                </span>
              </div>
            </div>
          </section>

          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="memorytask_error">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailError}</div>
            {props.selected.item.status === "failed" ? (
              <div className="mt-2 grid gap-2 text-xs text-subtext">
                <div className="text-danger">
                  {formatTaskCenterErrorText(props.selected.item.error_type, props.selected.item.error_message)}
                </div>
                <UserVisibleErrorsBlock errors={props.selected.item.user_visible_errors} />
                {extractHowToFix(props.selected.item.error).length > 0 ? (
                  <ul className="list-disc pl-5 text-[11px] text-subtext">
                    {extractHowToFix(props.selected.item.error).map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                <details className="rounded-atelier border border-border bg-canvas p-2">
                  <summary className="cursor-pointer select-none text-xs text-subtext">error（脱敏）</summary>
                  <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-ink">
                    {safeJsonStringify(props.selected.item.error ?? null)}
                  </pre>
                </details>
              </div>
            ) : (
              <div className="mt-2 text-xs text-subtext">{TASK_CENTER_COPY.detailNoError}</div>
            )}
          </section>
        </div>
      ) : null}

      {props.selected?.kind === "project_task" ? (
        <div className="mt-5 grid gap-3">
          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="projecttask_overview">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailOverview}</div>
            <div className="mt-2 grid gap-1 text-xs text-subtext">
              <div>
                Kind：<span className="font-mono text-ink">{props.selected.item.kind}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span>状态：</span>
                <StatusBadge status={props.selected.item.status} kind="task" />
              </div>
              <div>
                幂等键：<span className="font-mono text-ink">{props.selected.item.idempotency_key || "-"}</span>
              </div>
              <div>
                created_at：
                <span className="font-mono text-ink">
                  {String(
                    (props.selected.item.timings as Record<string, unknown> | null | undefined)?.created_at ?? "-",
                  )}
                </span>
              </div>
              <div>
                started_at：
                <span className="font-mono text-ink">
                  {String(
                    (props.selected.item.timings as Record<string, unknown> | null | undefined)?.started_at ?? "-",
                  )}
                </span>
              </div>
              <div>
                finished_at：
                <span className="font-mono text-ink">
                  {String(
                    (props.selected.item.timings as Record<string, unknown> | null | undefined)?.finished_at ?? "-",
                  )}
                </span>
              </div>
            </div>
          </section>

          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="projecttask_actions">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailActions}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                className="btn btn-secondary btn-sm"
                aria-label="刷新项目任务详情 (taskcenter_projecttask_refresh_detail)"
                onClick={props.onRefreshProjectTaskDetail}
                type="button"
              >
                {TASK_CENTER_COPY.detailRefreshProjectTask}
              </button>
              {props.selected.item.status === "failed" && !props.selectedProjectTaskRuntime?.batch ? (
                <button
                  className="btn btn-secondary btn-sm"
                  aria-label="重试项目任务 (taskcenter_projecttask_retry_detail)"
                  onClick={() => props.onRetryProjectTask(props.selected!.item.id)}
                  type="button"
                >
                  {TASK_CENTER_COPY.projectTasksRetry}
                </button>
              ) : null}
              {props.selected.item.status === "queued" && !props.selectedProjectTaskRuntime?.batch ? (
                <button
                  className="btn btn-secondary btn-sm"
                  aria-label="取消项目任务 (taskcenter_projecttask_cancel_detail)"
                  onClick={() => props.onCancelProjectTask(props.selected!.item.id)}
                  type="button"
                >
                  {TASK_CENTER_COPY.projectTasksCancel}
                </button>
              ) : null}
            </div>
            {props.projectTaskDetailLoading ? (
              <div className="mt-2 text-xs text-subtext">{TASK_CENTER_COPY.loading}</div>
            ) : null}
          </section>

          <ProjectTaskRuntimePanel
            runtime={props.selectedProjectTaskRuntime}
            loading={props.projectTaskRuntimeLoading}
            actionLoading={props.projectTaskBatchActionLoading}
            onRefresh={props.onRefreshProjectTaskRuntime}
            onPauseBatch={props.onPauseBatch}
            onResumeBatch={props.onResumeBatch}
            onRetryFailedBatch={props.onRetryFailedBatch}
            onSkipFailedBatch={props.onSkipFailedBatch}
            onCancelBatch={props.onCancelBatch}
          />

          {props.selectedProjectTaskRunId ? (
            <section
              className="rounded-atelier border border-border bg-surface p-3"
              aria-label="projecttask_generation_run"
            >
              <div className="text-sm text-ink">{TASK_CENTER_COPY.detailGenerationRun}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-subtext">
                <span>
                  run_id：<span className="font-mono text-ink">{props.selectedProjectTaskRunId}</span>
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  aria-label="复制 run_id (taskcenter_projecttask_copy_run_id)"
                  onClick={() => props.onCopyRunId(props.selectedProjectTaskRunId!)}
                  type="button"
                >
                  {TASK_CENTER_COPY.projectTaskRunIdCopyButton}
                </button>
                <a
                  className="btn btn-secondary btn-sm"
                  href={`/api/generation_runs/${encodeURIComponent(props.selectedProjectTaskRunId)}`}
                  target="_blank"
                  rel="noreferrer"
                  aria-label="打开运行记录 (taskcenter_projecttask_open_generation_run)"
                >
                  {TASK_CENTER_COPY.projectTaskRunIdOpenButton}
                </a>
              </div>
            </section>
          ) : null}

          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="projecttask_error">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailError}</div>
            {props.selected.item.status === "failed" ? (
              <div className="mt-2 grid gap-2 text-xs text-subtext">
                <div className="text-danger">
                  {formatTaskCenterErrorText(props.selected.item.error_type, props.selected.item.error_message)}
                </div>
                {extractHowToFix(props.selected.item.error).length > 0 ? (
                  <ul className="list-disc pl-5 text-[11px] text-subtext">
                    {extractHowToFix(props.selected.item.error).map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <div className="mt-2 text-xs text-subtext">{TASK_CENTER_COPY.detailNoError}</div>
            )}
          </section>

          {props.selected.item.kind === "table_ai_update" ? (
            <section className="rounded-atelier border border-border bg-surface p-3" aria-label="projecttask_changeset">
              <div className="text-sm text-ink">{TASK_CENTER_COPY.detailChangeSet}</div>
              {props.selectedProjectTaskChangeSetId ? (
                <div className="mt-2 grid gap-2 text-xs text-subtext">
                  <div>
                    change_set_id：<span className="font-mono text-ink">{props.selectedProjectTaskChangeSetId}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>状态：</span>
                    <StatusBadge status={String(props.liveChangeSetStatus || "unknown")} kind="change_set" />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={props.changeSetActionLoading || props.liveChangeSetStatus === "applied"}
                      onClick={() => props.onApplyChangeSet(props.selectedProjectTaskChangeSetId!)}
                      aria-label="应用变更集 (taskcenter_changeset_apply)"
                      type="button"
                    >
                      {props.changeSetActionLoading
                        ? TASK_CENTER_COPY.processing
                        : TASK_CENTER_COPY.applyChangeSetButton}
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={props.changeSetActionLoading || props.liveChangeSetStatus !== "applied"}
                      onClick={() => props.onRollbackChangeSet(props.selectedProjectTaskChangeSetId!)}
                      aria-label="回滚变更集 (taskcenter_changeset_rollback)"
                      type="button"
                    >
                      {props.changeSetActionLoading
                        ? TASK_CENTER_COPY.processing
                        : TASK_CENTER_COPY.rollbackChangeSetButton}
                    </button>
                  </div>
                  <div className="text-[11px] text-subtext">{TASK_CENTER_COPY.detailApplyRollbackHint}</div>
                </div>
              ) : (
                <div className="mt-2 text-xs text-subtext">{TASK_CENTER_COPY.detailMissingChangeSet}</div>
              )}
            </section>
          ) : null}

          <section className="rounded-atelier border border-border bg-surface p-3" aria-label="projecttask_results">
            <div className="text-sm text-ink">{TASK_CENTER_COPY.detailResults}</div>
            <div className="mt-2 grid gap-2">
              <details className="rounded-atelier border border-border bg-canvas p-2">
                <summary className="cursor-pointer select-none text-xs text-subtext">params（脱敏）</summary>
                <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-ink">
                  {safeJsonStringify(props.selected.item.params ?? null)}
                </pre>
              </details>
              <details className="rounded-atelier border border-border bg-canvas p-2">
                <summary className="cursor-pointer select-none text-xs text-subtext">result</summary>
                <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-ink">
                  {safeJsonStringify(props.selected.item.result ?? null)}
                </pre>
              </details>
              <details className="rounded-atelier border border-border bg-canvas p-2">
                <summary className="cursor-pointer select-none text-xs text-subtext">error（脱敏）</summary>
                <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-ink">
                  {safeJsonStringify(props.selected.item.error ?? null)}
                </pre>
              </details>
            </div>
          </section>
        </div>
      ) : null}

      {props.selected ? (
        <details className="mt-5 rounded-atelier border border-border bg-surface p-3">
          <summary className="cursor-pointer select-none text-sm text-ink">{TASK_CENTER_COPY.detailRawJson}</summary>
          <div className="mt-3 flex items-center justify-end">
            <button className="btn btn-secondary btn-sm" onClick={props.onCopyRawJson} type="button">
              {TASK_CENTER_COPY.detailCopyDebug}
            </button>
          </div>
          <pre className="mt-2 whitespace-pre-wrap break-words rounded-atelier border border-border bg-canvas p-3 text-xs text-ink">
            {safeJsonStringify(props.selected.item)}
          </pre>
        </details>
      ) : null}
    </Drawer>
  );
}
