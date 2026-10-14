import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://mtgl.anujajay.com"),
  title: {
    default: "MTGL — Movies, TV, and games you remember",
    template: "%s | MTGL",
  },
  description: "A home for the movies, shows, and games you remember.",
  applicationName: "MTGL",
  openGraph: {
    type: "website",
    siteName: "MTGL",
    title: "MTGL — Movies, TV, and games you remember",
    description: "A home for the movies, shows, and games you remember.",
    url: "https://mtgl.anujajay.com",
  },
  twitter: {
    card: "summary",
    title: "MTGL — Movies, TV, and games you remember",
    description: "A home for the movies, shows, and games you remember.",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const clerkReady = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY);
  return (
    <html lang="en">
      <body>{clerkReady ? <ClerkProvider appearance={{ variables: { colorPrimary: "#8585ff", colorPrimaryForeground: "#0d0d33", colorForeground: "#f5f5f4", colorBackground: "#151820", colorInput: "#20242d", colorInputForeground: "#f5f5f4", colorMutedForeground: "#b4bac4", borderRadius: "10px" } }}>{children}</ClerkProvider> : children}</body>
    </html>
  );
}
