import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "Media Catalog",
  description: "A home for the movies, shows, and games you remember.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const clerkReady = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY);
  return (
    <html lang="en">
      <body>{clerkReady ? <ClerkProvider>{children}</ClerkProvider> : children}</body>
    </html>
  );
}
