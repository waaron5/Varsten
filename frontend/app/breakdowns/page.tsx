import { redirect } from "next/navigation";

export default function BreakdownsRedirect() {
  redirect("/analysis/spend");
}
