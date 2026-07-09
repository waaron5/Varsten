import fs from "fs";
import path from "path";
import { cache } from "react";

export type DocFrontmatter = {
  title: string;
  description: string;
  slug: string;
  category: string;
  order: number;
  updatedAt: string;
};

export type DocPage = DocFrontmatter & {
  body: string;
};

const docsDirectory = path.join(process.cwd(), "content", "docs");

function parseFrontmatter(raw: string, fileName: string): DocPage {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) throw new Error(`Missing frontmatter in ${fileName}`);

  const fields = match[1].split("\n").reduce<Record<string, string>>((acc, line) => {
    const separator = line.indexOf(":");
    if (separator === -1) return acc;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^["']|["']$/g, "");
    acc[key] = value;
    return acc;
  }, {});

  const required = ["title", "slug", "category", "order", "updatedAt"] as const;
  for (const key of required) {
    if (!fields[key]) throw new Error(`Missing ${key} in ${fileName}`);
  }

  const order = Number(fields.order);
  if (!Number.isFinite(order)) throw new Error(`Invalid order in ${fileName}`);

  const body = match[2].trim();
  const description = fields.description || descriptionFromMarkdown(body);
  if (!description) throw new Error(`Missing description in ${fileName}`);

  return {
    title: fields.title,
    description,
    slug: fields.slug,
    category: fields.category,
    order,
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

export function descriptionFromMarkdown(markdown: string) {
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

export function getDocsByCategory() {
  return getAllDocs().reduce<Record<string, DocPage[]>>((groups, doc) => {
    groups[doc.category] = groups[doc.category] || [];
    groups[doc.category].push(doc);
    return groups;
  }, {});
}
