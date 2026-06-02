import { PublicReportView } from "@/components/ReportsViews";

export default async function SharedReportPage({
  params,
}: {
  params: Promise<{ shareToken: string }>;
}) {
  const { shareToken } = await params;
  return <PublicReportView shareToken={shareToken} />;
}
