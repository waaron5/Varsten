import type { ReactNode } from "react";

type SectionIntroProps = {
  eyebrow: string;
  title: string;
  children: ReactNode;
};

export function SectionIntro({ eyebrow, title, children }: SectionIntroProps) {
  return (
    <div className="grid gap-10 border-b border-border py-16 md:grid-cols-12 md:py-24">
      <div className="md:col-span-4">
        <div className="mono mb-4 text-[11px] uppercase tracking-[0.28em] text-ink-soft">
          {eyebrow}
        </div>
        <h2 className="text-[36px] font-medium leading-[1.05] tracking-[-0.02em] text-ink md:text-[48px]">
          {title}
        </h2>
      </div>
      <div className="max-w-xl md:col-span-7 md:col-start-6">{children}</div>
    </div>
  );
}
