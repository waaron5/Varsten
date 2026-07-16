import fs from "fs";
import path from "path";
import { cache } from "react";

type DocFrontmatter = {
  title: string;
  description: string;
  slug: string;
  category: string;
  order: number;
  updatedAt: string;
};

type DocPage = DocFrontmatter & {
  body: string;
};

const docsDirectory = path.join(process.cwd(), "content", "docs");
const requiredFrontmatterFields = ["title", "slug", "category", "order", "updatedAt"] as const;

function splitFrontmatter(raw: string, fileName: string): RegExpMatchArray {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) throw new Error(`Missing frontmatter in ${fileName}`);
  return match;
}

function frontmatterFields(frontmatter: string): Record<string, string> {
  return frontmatter.split("\n").reduce<Record<string, string>>((acc, line) => {
    const separator = line.indexOf(":");
    if (separator === -1) return acc;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^["']|["']$/g, "");
    acc[key] = value;
    return acc;
  }, {});
}

function requireFrontmatter(fields: Record<string, string>, fileName: string) {
  for (const key of requiredFrontmatterFields) {
    if (!fields[key]) throw new Error(`Missing ${key} in ${fileName}`);
  }
}

function parseOrder(value: string, fileName: string): number {
  const order = Number(value);
  if (!Number.isFinite(order)) throw new Error(`Invalid order in ${fileName}`);
  return order;
}

function parseFrontmatter(raw: string, fileName: string): DocPage {
  const match = splitFrontmatter(raw, fileName);
  const fields = frontmatterFields(match[1]);
  requireFrontmatter(fields, fileName);

  const body = match[2].trim();
  const description = fields.description || descriptionFromMarkdown(body);
  if (!description) throw new Error(`Missing description in ${fileName}`);

  return {
    title: fields.title,
    description,
    slug: fields.slug,
    category: fields.category,
    order: parseOrder(fields.order, fileName),
    updatedAt: fields.updatedAt,
    body,
  };
}

function markdownFiles() {
  return fs
    .readdirSync(docsDirectory)
    .filter((file) => file.endsWith(".md"))
    .sort();
}

function descriptionFromMarkdown(markdown: string) {
  const clean = markdown
    .replace(/```[\s\S]*?```/g, "")
    .split("\n")
    .map((line) =>
      line
        .replace(/^#{1,6}\s+/, "")
        .replace(/^[-*]\s+/, "")
        .replace(/^\d+\.\s+/, "")
        .trim(),
    )
    .filter(Boolean)
    .find((line) => !line.startsWith("|"));

  return clean ? clean.replace(/[`*_]/g, "").slice(0, 156) : "";
}

export const getAllDocs = cache((): DocPage[] => {
  return markdownFiles()
    .map((fileName) => parseFrontmatter(fs.readFileSync(path.join(docsDirectory, fileName), "utf8"), fileName))
    .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));
});

export function getDoc(slug: string) {
  return getAllDocs().find((doc) => doc.slug === slug) ?? null;
}
