import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownPreviewRendererProps = {
  content: string;
  className?: string;
};

export function MarkdownPreviewRenderer(props: MarkdownPreviewRendererProps) {
  return (
    <div className={props.className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{props.content}</ReactMarkdown>
    </div>
  );
}
