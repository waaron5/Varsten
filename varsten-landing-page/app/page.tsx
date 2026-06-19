import { SiteHeader } from "@/components/site-header"
import { Hero } from "@/components/hero"
import { TrustBar } from "@/components/trust-bar"
import { ProblemSection } from "@/components/problem-section"
import { ProductPillars } from "@/components/product-pillars"
import { HowItWorks } from "@/components/how-it-works"
import { SavingsLevers } from "@/components/savings-levers"
import { PricingSection } from "@/components/pricing-section"
import { SecuritySection } from "@/components/security-section"
import { OnboardingFlow } from "@/components/onboarding-flow"
import { FaqSection } from "@/components/faq-section"
import { CtaSection } from "@/components/cta-section"
import { SiteFooter } from "@/components/site-footer"

export default function Page() {
  return (
    <div className="flex min-h-screen flex-col overflow-x-hidden bg-background">
      <SiteHeader />
      <main className="flex-1">
        <Hero />
        <TrustBar />
        <ProblemSection />
        <ProductPillars />
        <HowItWorks />
        <SavingsLevers />
        <PricingSection />
        <SecuritySection />
        <OnboardingFlow />
        <FaqSection />
        <CtaSection />
      </main>
      <SiteFooter />
    </div>
  )
}
