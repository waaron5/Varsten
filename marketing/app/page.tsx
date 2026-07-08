"use client";

import { Nav } from "@/components/varsten/Nav";
import { Hero } from "@/components/varsten/Hero";
import { Levers } from "@/components/varsten/Levers";
import { Integrations } from "@/components/varsten/Integrations";
import { Pricing } from "@/components/varsten/Pricing";
import { Footer } from "@/components/varsten/Footer";

export default function Page() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Nav />
      <main>
        <Hero />
        <Levers />
        <Integrations />
        <Pricing />
      </main>
      <Footer />
    </div>
  );
}
