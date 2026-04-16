import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="text-lcars-orange font-mono text-sm font-bold tracking-[0.2em] uppercase mt-4 mb-2 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-lcars-amber font-mono text-xs font-bold tracking-[0.2em] uppercase mt-4 mb-1.5 first:mt-0 border-b border-lcars-border pb-1">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-lcars-cyan font-mono text-xs font-bold tracking-widest uppercase mt-3 mb-1 first:mt-0">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="text-sm text-lcars-text leading-relaxed mb-2 last:mb-0">
      {children}
    </p>
  ),
  strong: ({ children }) => (
    <strong className="text-lcars-text font-bold">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="text-lcars-muted italic">{children}</em>
  ),
  code: ({ children, className }) => {
    const isBlock = className?.startsWith("language-");
    if (isBlock) {
      return (
        <code className="block bg-black/30 border border-lcars-border text-lcars-green font-mono text-xs p-3 my-2 whitespace-pre overflow-x-auto">
          {children}
        </code>
      );
    }
    return (
      <code className="bg-black/30 text-lcars-green font-mono text-xs px-1 py-0.5 rounded-sm">
        {children}
      </code>
    );
  },
  pre: ({ children }) => <>{children}</>,
  ul: ({ children }) => (
    <ul className="space-y-1 mb-2 pl-3">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="space-y-1 mb-2 pl-3 list-decimal list-inside">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="text-sm text-lcars-text leading-relaxed flex gap-2">
      <span className="text-lcars-orange shrink-0 mt-0.5">▸</span>
      <span>{children}</span>
    </li>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-lcars-orange pl-3 my-2 text-lcars-muted italic">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-lcars-cyan hover:text-lcars-amber underline transition-colors"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="border-lcars-border my-3" />,
};

export default function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="space-y-1">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
