import type { Metadata } from "next";

export const metadata: Metadata = { title: "Shared library · MTGL", robots: { index: false, follow: false } };

type SharedTitle = { id: string; name: string; media_type: "movie" | "tv" | "game"; poster_url: string | null; release_date: string | null };
type SharedEntry = { title: SharedTitle; status: string; rating_half_steps: number | null; lists: string[] };
type SharedLibrary = { display_name: string; expires_at: string; entries: SharedEntry[] };

export default async function SharedLibraryPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const api = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  let library: SharedLibrary | null = null;
  try {
    const response = await fetch(`${api}/api/public/shares/${encodeURIComponent(token)}`, { cache: "no-store" });
    if (response.ok) library = await response.json() as SharedLibrary;
  } catch { /* A missing API produces the same private unavailable state. */ }
  return <main className="shared-page content-wrap">
    <meta name="referrer" content="no-referrer" />
    <a className="shared-home" href="/">MTGL</a>
    {library ? <><p className="eyebrow">A SHARED COLLECTION</p><h1>{library.display_name}&apos;s library</h1><p className="page-subtitle">A glimpse of the movies, series, and games they keep close.</p>
      {(["movie", "tv", "game"] as const).map((kind) => {
        const entries = library!.entries.filter((entry) => entry.title.media_type === kind);
        if (!entries.length) return null;
        return <section className="shared-group" key={kind}><h2>{kind === "tv" ? "TV series" : kind === "movie" ? "Movies" : "Games"}</h2><div className="poster-grid">{entries.map((entry) => <article className="title-card" key={entry.title.id}><div className="poster-art">{entry.title.poster_url ? <img src={entry.title.poster_url} alt="" loading="lazy" referrerPolicy="no-referrer"/> : <span aria-hidden="true">{entry.title.name.slice(0, 1)}</span>}</div><div className="card-copy"><span>{entry.title.release_date?.slice(0, 4) || "Date unknown"} · {entry.status.replaceAll("_", " ")}</span><h3>{entry.title.name}</h3>{(entry.rating_half_steps || entry.lists.length > 0) && <p className="card-personal">{entry.rating_half_steps && <span>{(entry.rating_half_steps / 2).toFixed(1)} ★</span>}{entry.lists.map((name) => <span key={name}>{name}</span>)}</p>}</div></article>)}</div></section>;
      })}
      {!library.entries.length && <p className="quiet-note">This collection is empty for now.</p>}
    </> : <div className="shared-unavailable"><h1>This link is unavailable.</h1><p>It may have expired or been turned off by its owner.</p><a href="/">Explore the catalog</a></div>}
  </main>;
}
