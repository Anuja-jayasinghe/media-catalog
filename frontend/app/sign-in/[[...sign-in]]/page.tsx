import type { Metadata } from "next";
import { AuthScreen } from "../../auth-screen";
import { safeReturnTo } from "../../auth-return";

export const metadata: Metadata = { title: "Sign in · MTGL", robots: { index: false, follow: false } };

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ return_to?: string }> }) {
  const { return_to } = await searchParams;
  return <AuthScreen mode="sign-in" returnTo={safeReturnTo(return_to)}/>;
}
