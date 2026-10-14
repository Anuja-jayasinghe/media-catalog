import type { Metadata } from "next";
import { GuestCatalog, SignedCatalog } from "./catalog";

type PageProps = {
  searchParams: Promise<{ view?: string; q?: string; title?: string }>;
};

const catalogViews = {
  movie: { title: "Movies", description: "Discover movies to watch and remember." },
  tv: { title: "TV series", description: "Discover TV series to watch and remember." },
  game: { title: "Games", description: "Discover games to play and remember." },
} as const;

export async function generateMetadata({ searchParams }: PageProps): Promise<Metadata> {
  const { view, q, title } = await searchParams;
  const category = view && view in catalogViews ? catalogViews[view as keyof typeof catalogViews] : null;
  const pageLabel = category?.title ?? (view === "search" ? "Search" : view === "library" ? "My library" : null);
  const pageTitle = pageLabel ? `${pageLabel} | MTGL` : null;
  const description = category?.description ?? "A home for the movies, shows, and games you remember.";
  const canonical = category ? `/?view=${view}` : "/";
  const privateOrFiltered = view === "search" || view === "library" || Boolean(q || title);

  return {
    ...(pageTitle ? { title: pageTitle } : {}),
    description,
    alternates: { canonical },
    ...(privateOrFiltered ? { robots: { index: false, follow: true } } : {}),
    openGraph: { type: "website", title: pageTitle ?? "MTGL", description, url: canonical },
    twitter: { card: "summary", title: pageTitle ?? "MTGL", description },
  };
}

export default function Home() {
  const clerkReady = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY);
  return clerkReady ? <SignedCatalog /> : <GuestCatalog />;
}
