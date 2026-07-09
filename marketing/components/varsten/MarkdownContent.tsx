import type { ReactNode } from "react";
import { TrackedCodeBlock } from "./TrackedCodeBlock";

type Block =
  | { type: "heading"; level: 2 | 3 | 4; text: string }
  | { type: "paragraph"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "code"; language?: string; code: string };

function parseMarkdown(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const language = line.slice(3).trim() || undefined;
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", language, code: code.join("\n") });
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{2,4})\s+(.*)$/);
    if (heading) {
      blocks.push({
        type: "heading",
        level: heading[1].length as 2 | 3 | 4,
        text: heading[2].trim(),
      });
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*]\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+\.\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    const paragraph: string[] = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("```") &&
      !/^(#{2,4})\s+/.test(lines[index]) &&
      !/^[-*]\s+/.test(lines[index]) &&
      !/^\d+\.\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }

  return blocks;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];

    if (token.startsWith("**")) {
      nodes.push(
        <strong key={`${token}-${match.index}`} className="font-semibold text-ink">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`")) {
      nodes.push(
        <code key={`${token}-${match.index}`} className="border border-border bg-muted px-1 py-0.5 text-[0.92em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (link) {
        nodes.push(
          <a key={`${token}-${match.index}`} href={link[2]} className="text-blueprint underline underline-offset-4">
            {link[1]}
          </a>,
        );
      }
    }

    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

export function MarkdownContent({ markdown, docSlug }: { markdown: string; docSlug: string }) {
  const blocks = parseMarkdown(markdown);

  return (
    <div className="docs-markdown max-w-3xl">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          const id = block.text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
          const className =
            block.level === 2
              ? "mt-10 scroll-mt-24 text-[28px] font-semibold tracking-[-0.01em] text-ink"
              : "mt-8 scroll-mt-24 text-[20px] font-semibold text-ink";

          if (block.level === 2) {
            return (
              <h2 id={id} key={`${block.text}-${index}`} className={className}>
                {block.text}
              </h2>
            );
          }

          if (block.level === 3) {
            return (
              <h3 id={id} key={`${block.text}-${index}`} className={className}>
                {block.text}
              </h3>
            );
          }

          return (
            <h4 id={id} key={`${block.text}-${index}`} className={className}>
              {block.text}
            </h4>
          );
        }

        if (block.type === "paragraph") {
          return (
            <p key={`${block.text}-${index}`} className="mt-4 text-[15px] leading-7 text-ink-soft">
              {renderInline(block.text)}
            </p>
          );
        }

        if (block.type === "ul") {
          return (
            <ul key={`ul-${index}`} className="mt-4 grid list-disc gap-2 pl-5 text-[15px] leading-7 text-ink-soft">
              {block.items.map((item) => (
                <li key={item}>{renderInline(item)}</li>
              ))}
            </ul>
          );
        }

        if (block.type === "ol") {
          return (
            <ol key={`ol-${index}`} className="mt-4 grid list-decimal gap-2 pl-5 text-[15px] leading-7 text-ink-soft">
              {block.items.map((item) => (
                <li key={item}>{renderInline(item)}</li>
              ))}
            </ol>
          );
        }

        return (
          <TrackedCodeBlock
            key={`code-${index}`}
            code={block.code}
            language={block.language}
            docSlug={docSlug}
          />
        );
      })}
    </div>
  );
}
