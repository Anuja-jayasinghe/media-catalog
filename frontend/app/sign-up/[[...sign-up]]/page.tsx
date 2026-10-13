import type { Metadata } from "next";
import { AuthScreen } from "../../auth-screen";
import { safeReturnTo } from "../../auth-return";

export const metadata: Metadata = { title: "Create account · MTGL" };

export default async function SignUpPage({ searchParams }: { searchParams: Promise<{ return_to?: string }> }) {
  const { return_to } = await searchParams;
  return <AuthScreen mode="sign-up" returnTo={safeReturnTo(return_to)}/>;
}
