import type { ReactNode } from "react";
import { TrackedCodeBlock } from "./TrackedCodeBlock";

type Block =
  | { type: "heading"; level: 2 | 3 | 4; text: string }
  | { type: "paragraph"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "code"; language?: string; code: string };

type ParsedBlock = { block?: Block; nextIndex: number };
type BlockParser = (lines: string[], index: number) => ParsedBlock | null;

const headingPattern = /^(#{2,4})\s+(.*)$/;
const unorderedListPattern = /^[-*]\s+/;
const orderedListPattern = /^\d+\.\s+/;

function parseBlankLine(lines: string[], index: number): ParsedBlock | null {
  return lines[index].trim() ? null : { nextIndex: index + 1 };
}

function collectCodeLines(lines: string[], startIndex: number): { code: string[]; nextIndex: number } {
  const code: string[] = [];
  let nextIndex = startIndex;
  while (nextIndex < lines.length && !lines[nextIndex].startsWith("```")) {
    code.push(lines[nextIndex]);
    nextIndex += 1;
  }
  return { code, nextIndex };
}

function parseCodeBlock(lines: string[], index: number): ParsedBlock | null {
  const line = lines[index];
  if (!line.startsWith("```")) return null;
  const language = line.slice(3).trim() || undefined;
  const { code, nextIndex } = collectCodeLines(lines, index + 1);
  return { block: { type: "code", language, code: code.join("\n") }, nextIndex: nextIndex + 1 };
}

function parseHeadingBlock(lines: string[], index: number): ParsedBlock | null {
  const heading = lines[index].match(headingPattern);
  if (!heading) return null;
  return {
    block: {
      type: "heading",
      level: heading[1].length as 2 | 3 | 4,
      text: heading[2].trim(),
    },
    nextIndex: index + 1,
  };
}

function parseListBlock(
  lines: string[],
  index: number,
  pattern: RegExp,
  type: "ul" | "ol",
): ParsedBlock | null {
  if (!pattern.test(lines[index])) return null;
  const items: string[] = [];
  let nextIndex = index;
  while (nextIndex < lines.length && pattern.test(lines[nextIndex])) {
    items.push(lines[nextIndex].replace(pattern, "").trim());
    nextIndex += 1;
  }
  return { block: { type, items }, nextIndex };
}

function parseUnorderedListBlock(lines: string[], index: number): ParsedBlock | null {
  return parseListBlock(lines, index, unorderedListPattern, "ul");
}

function parseOrderedListBlock(lines: string[], index: number): ParsedBlock | null {
  return parseListBlock(lines, index, orderedListPattern, "ol");
}

const blockParsers: BlockParser[] = [
  parseBlankLine,
  parseCodeBlock,
  parseHeadingBlock,
  parseUnorderedListBlock,
  parseOrderedListBlock,
];

function startsNewBlock(line: string): boolean {
  return (
    line.startsWith("```") ||
    headingPattern.test(line) ||
    unorderedListPattern.test(line) ||
    orderedListPattern.test(line)
  );
}

function parseParagraphBlock(lines: string[], index: number): ParsedBlock {
  const paragraph: string[] = [lines[index].trim()];
  let nextIndex = index + 1;
  while (nextIndex < lines.length && lines[nextIndex].trim() && !startsNewBlock(lines[nextIndex])) {
    paragraph.push(lines[nextIndex].trim());
    nextIndex += 1;
  }
  return { block: { type: "paragraph", text: paragraph.join(" ") }, nextIndex };
}

function parseKnownBlock(lines: string[], index: number): ParsedBlock {
  for (const parser of blockParsers) {
    const parsed = parser(lines, index);
    if (parsed) return parsed;
  }
  return parseParagraphBlock(lines, index);
}

function parseMarkdown(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.split("\n");
  let index = 0;

  while (index < lines.length) {
    const parsed = parseKnownBlock(lines, index);
    if (parsed.block) blocks.push(parsed.block);
    index = parsed.nextIndex;
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
    nodes.push(renderInlineToken(token, match.index));
    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function renderInlineToken(token: string, index: number): ReactNode {
  if (token.startsWith("**")) {
    return (
      <strong key={`${token}-${index}`} className="font-semibold text-ink">
        {token.slice(2, -2)}
      </strong>
    );
  }

  if (token.startsWith("`")) {
    return (
      <code key={`${token}-${index}`} className="border border-border bg-muted px-1 py-0.5 text-[0.92em]">
        {token.slice(1, -1)}
      </code>
    );
  }

  return renderInlineLink(token, index);
}

function renderInlineLink(token: string, index: number): ReactNode {
  const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
  if (!link) return token;
  return (
    <a key={`${token}-${index}`} href={link[2]} className="text-blueprint underline underline-offset-4">
      {link[1]}
    </a>
  );
}

function headingId(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function headingClass(level: 2 | 3 | 4): string {
  return level === 2
    ? "mt-10 scroll-mt-24 text-[28px] font-semibold tracking-[-0.01em] text-ink"
    : "mt-8 scroll-mt-24 text-[20px] font-semibold text-ink";
}

function renderHeadingBlock(block: Extract<Block, { type: "heading" }>, index: number) {
  const props = { id: headingId(block.text), className: headingClass(block.level), children: block.text };
  const key = `${block.text}-${index}`;
  const elements = {
    2: <h2 key={key} {...props} />,
    3: <h3 key={key} {...props} />,
    4: <h4 key={key} {...props} />,
  };
  return elements[block.level];
}

function renderParagraphBlock(block: Extract<Block, { type: "paragraph" }>, index: number) {
  return (
    <p key={`${block.text}-${index}`} className="mt-4 text-[15px] leading-7 text-ink-soft">
      {renderInline(block.text)}
    </p>
  );
}

function renderUnorderedListBlock(block: Extract<Block, { type: "ul" }>, index: number) {
  return (
    <ul key={`ul-${index}`} className="mt-4 grid list-disc gap-2 pl-5 text-[15px] leading-7 text-ink-soft">
      {block.items.map((item) => (
        <li key={item}>{renderInline(item)}</li>
      ))}
    </ul>
  );
}

function renderOrderedListBlock(block: Extract<Block, { type: "ol" }>, index: number) {
  return (
    <ol key={`ol-${index}`} className="mt-4 grid list-decimal gap-2 pl-5 text-[15px] leading-7 text-ink-soft">
      {block.items.map((item) => (
        <li key={item}>{renderInline(item)}</li>
      ))}
    </ol>
  );
}

function renderCodeBlock(block: Extract<Block, { type: "code" }>, index: number, docSlug: string) {
  return <TrackedCodeBlock key={`code-${index}`} code={block.code} language={block.language} docSlug={docSlug} />;
}

const blockRenderers = {
  heading: renderHeadingBlock,
  paragraph: renderParagraphBlock,
  ul: renderUnorderedListBlock,
  ol: renderOrderedListBlock,
  code: renderCodeBlock,
} satisfies {
  [K in Block["type"]]: (block: Extract<Block, { type: K }>, index: number, docSlug: string) => ReactNode;
};

function renderBlock(block: Block, index: number, docSlug: string): ReactNode {
  const renderer = blockRenderers[block.type] as (block: Block, index: number, docSlug: string) => ReactNode;
  return renderer(block, index, docSlug);
}

export function MarkdownContent({ markdown, docSlug }: { markdown: string; docSlug: string }) {
  const blocks = parseMarkdown(markdown);

  return (
    <div className="docs-markdown max-w-3xl">
      {blocks.map((block, index) => renderBlock(block, index, docSlug))}
    </div>
  );
}
