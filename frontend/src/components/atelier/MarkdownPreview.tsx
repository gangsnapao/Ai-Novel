import { Suspense, lazy, type ReactNode } from "react";

import { importWithChunkRetry } from "../../lib/lazyImportRetry";

export async function preloadMarkdownPreviewRenderer() {
  return importWithChunkRetry(() => import("./MarkdownPreviewRenderer"));
}

const LazyMarkdownPreviewRenderer = lazy(async () => {
  const mod = await preloadMarkdownPreviewRenderer();
  return { default: mod.MarkdownPreviewRenderer };
});

type MarkdownPreviewProps = {
  content: string;
  className?: string;
  emptyPlaceholder?: string;
  fallback?: ReactNode;
};

export function MarkdownPreview(props: MarkdownPreviewProps) {
  const renderedContent = props.content.trim() ? props.content : props.emptyPlaceholder ?? "_（空）_";

  return (
    <Suspense fallback={props.fallback ?? <div className={props.className}>加载预览中...</div>}>
      <LazyMarkdownPreviewRenderer className={props.className} content={renderedContent} />
    </Suspense>
  );
}
