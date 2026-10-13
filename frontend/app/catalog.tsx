"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useMemo, useState } from "react";

type MediaType = "all" | "movie" | "tv" | "game";
type Status = "planned" | "in_progress" | "completed" | "dropped";
type Title = {
  id: string;
  media_type: Exclude<MediaType, "all">;
  provider: string;
  provider_id: string;
  name: string;
  overview: string;
  poster_url: string | null;
  release_date: string | null;
};
type Entry = {
  title: Title;
  status: Status;
  completed_on: string | null;
  date_precision: string;
  updated_at: string;
};
type SearchResponse = { results: Title[]; warnings: string[]; cached: boolean };
type DiscoverSection = "recent" | "upcoming";
type TokenGetter = () => Promise<string | null>;

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const tabs: { value: MediaType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "movie", label: "Movies" },
  { value: "tv", label: "TV series" },
  { value: "game", label: "Games" },
];
const statuses: { value: Status; label: string }[] = [
  { value: "planned", label: "Plan to watch / play" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "dropped", label: "Dropped" },
];
const typeNames = { movie: "Movie", tv: "TV series", game: "Game" };

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export function SignedCatalog() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const tokenGetter = useCallback(() => getToken(), [getToken]);
  const authControl = !isLoaded ? (
    <span className="auth-loading">Loading account…</span>
  ) : isSignedIn ? (
    <UserButton />
  ) : (
    <SignInButton mode="modal"><button className="header-sign-in">Sign in</button></SignInButton>
  );
  return <Catalog signedIn={Boolean(isSignedIn)} authConfigured tokenGetter={tokenGetter} authControl={authControl} />;
}

export function GuestCatalog() {
  return <Catalog signedIn={false} authConfigured={false} authControl={<span className="setup-label">Sign-in setup pending</span>} />;
}

function Catalog({
  signedIn, authConfigured, tokenGetter, authControl,
}: {
  signedIn: boolean;
  authConfigured: boolean;
  tokenGetter?: TokenGetter;
  authControl: React.ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MediaType>("all");
  const [view, setView] = useState<"explore" | "library">("explore");
  const [results, setResults] = useState<Title[]>([]);
  const [discover, setDiscover] = useState<Record<DiscoverSection, Title[]>>({ recent: [], upcoming: [] });
  const [discoverLoading, setDiscoverLoading] = useState(true);
  const [discoverError, setDiscoverError] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [searching, setSearching] = useState(false);
  const [loadingLibrary, setLoadingLibrary] = useState(false);
  const [warning, setWarning] = useState("");
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(12);
  const savedById = useMemo(() => new Map(entries.map((entry) => [entry.title.id, entry])), [entries]);

  const loadLibrary = useCallback(async () => {
    if (!signedIn || !tokenGetter) {
      setEntries([]);
      return;
    }
    setLoadingLibrary(true);
    try {
      const token = await tokenGetter();
      if (!token) throw new Error("Your session is not ready. Please sign in again.");
      const response = await fetch(`${apiBase}/api/library`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (!response.ok) throw new Error(await errorMessage(response));
      setEntries(await response.json());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load your library");
    } finally {
      setLoadingLibrary(false);
    }
  }, [signedIn, tokenGetter]);

  useEffect(() => { void loadLibrary(); }, [loadLibrary]);

  useEffect(() => {
    const controller = new AbortController();
    setDiscover({ recent: [], upcoming: [] });
    setDiscoverLoading(true);
    setDiscoverError("");
    const load = async () => {
      for (const section of ["recent", "upcoming"] as const) {
        try {
          const params = new URLSearchParams({ section, media_type: filter });
          const response = await fetch(`${apiBase}/api/discover?${params}`, { signal: controller.signal });
          if (!response.ok) throw new Error(await errorMessage(response));
          const body: SearchResponse = await response.json();
          if (!controller.signal.aborted) {
            setDiscover((current) => ({ ...current, [section]: body.results }));
            if (body.warnings.length) setDiscoverError(body.warnings.join(" · "));
          }
        } catch (cause) {
          if (!controller.signal.aborted) setDiscoverError(cause instanceof Error ? cause.message : "Could not load releases");
        }
      }
      if (!controller.signal.aborted) setDiscoverLoading(false);
    };
    void load();
    return () => controller.abort();
  }, [filter]);

  useEffect(() => {
    const trimmed = query.trim();
    setVisibleCount(12);
    if (trimmed.length < 2) {
      setResults([]);
      setWarning("");
      setSearching(false);
      return;
    }
    setResults([]);
    setSearching(true);
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setError("");
      try {
        const params = new URLSearchParams({ q: trimmed, media_type: filter });
        const response = await fetch(`${apiBase}/api/search?${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error(await errorMessage(response));
        const body: SearchResponse = await response.json();
        setResults(body.results);
        setWarning(body.warnings.join(" · "));
      } catch (cause) {
        if (!controller.signal.aborted) {
          setResults([]);
          setError(cause instanceof Error ? cause.message : "Search failed");
        }
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, 450);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query, filter]);

  async function save(titleId: string, status: Status | "") {
    if (!signedIn || !tokenGetter) return;
    setSavingId(titleId);
    setError("");
    try {
      const token = await tokenGetter();
      if (!token) throw new Error("Your session is not ready. Please sign in again.");
      const response = await fetch(`${apiBase}/api/library/${titleId}`, {
        method: status ? "PUT" : "DELETE",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: status ? JSON.stringify({ status }) : undefined,
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      await loadLibrary();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save title");
    } finally {
      setSavingId(null);
    }
  }

  const shown = view === "library" ? entries.map((entry) => entry.title) : results.slice(0, visibleCount);
  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark" aria-hidden="true">◧</span><span>Media Catalog</span></div>
        <nav className="topnav" aria-label="Main navigation">
          <button className={view === "explore" ? "active" : ""} onClick={() => setView("explore")}>Explore</button>
          {signedIn && <button className={view === "library" ? "active" : ""} onClick={() => setView("library")}>My library <span className="nav-count">{entries.length}</span></button>}
        </nav>
        <div className="account">{authControl}</div>
      </header>

      {view === "explore" ? (
        <>
          <section className="hero">
            <p className="eyebrow">YOUR STORIES, IN ONE PLACE</p>
            <h1>Remember what you<br /><em>loved.</em></h1>
            <p className="hero-copy">Find movies, series, and games together. Keep the ones that became part of your story.</p>
            <label className="searchbox">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4.5 4.5"/></svg>
              <span className="sr-only">Search titles</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search movies, TV series, and games" autoComplete="off" maxLength={120} />
              {query && <button className="clear" onClick={() => setQuery("")} aria-label="Clear search">×</button>}
            </label>
            <div className="filters" role="group" aria-label="Filter by media type">
              {tabs.map((tab) => <button key={tab.value} className={filter === tab.value ? "selected" : ""} onClick={() => setFilter(tab.value)}>{tab.label}</button>)}
            </div>
          </section>
          <section className="content" aria-live="polite">
            <div className="section-heading"><div><p className="eyebrow">EXPLORE THE CATALOG</p><h2>{query.trim().length >= 2 ? `Results for “${query.trim()}”` : "Find your next title"}</h2></div><span className="result-count">{searching ? "Searching…" : query.trim().length >= 2 ? `${results.length} titles` : ""}</span></div>
            {!query.trim() && <p className="browse-intro">Browse recent and upcoming releases, or search for something you already know.</p>}
            {query.trim().length === 1 && <p className="empty-state">Type one more character to search.</p>}
            {query.trim().length >= 2 && !searching && results.length === 0 && !error && <p className="empty-state">No matches found yet. Try another title or spelling.</p>}
            {warning && <p className="notice">{warning}</p>}
            {error && <p className="notice error" role="alert">{error}</p>}
            {query.trim().length >= 2 && <div className="card-grid">{shown.map((title) => <TitleCard key={title.id} title={title} entry={savedById.get(title.id)} saving={savingId === title.id} signedIn={signedIn} authConfigured={authConfigured} onSave={save} />)}</div>}
            {query.trim().length >= 2 && results.length > visibleCount && <button className="show-more" onClick={() => setVisibleCount((count) => count + 12)}>Show more titles</button>}
            {!query.trim() && <>
              {discoverError && <p className="notice" role="status">{discoverError}</p>}
              <DiscoverRail label="NEWLY RELEASED" title="Fresh to explore" titles={discover.recent} loading={discoverLoading} savedById={savedById} savingId={savingId} signedIn={signedIn} authConfigured={authConfigured} onSave={save} />
              <DiscoverRail label="ON THE HORIZON" title="Coming soon" titles={discover.upcoming} loading={discoverLoading} savedById={savedById} savingId={savingId} signedIn={signedIn} authConfigured={authConfigured} onSave={save} />
            </>}
          </section>
        </>
      ) : (
        <section className="content library-content" aria-live="polite">
          <div className="section-heading"><div><p className="eyebrow">YOUR COLLECTION</p><h1>My library</h1><p className="library-subtitle">A home for everything you plan, watch, and play.</p></div><span className="result-count">{entries.length} titles</span></div>
          {error && <p className="notice error" role="alert">{error}</p>}
          {loadingLibrary && <p className="empty-state">Loading your library…</p>}
          {!loadingLibrary && entries.length === 0 && <div className="empty-library"><span aria-hidden="true">✦</span><h2>Your library starts with one title.</h2><p>Search for something you know and save it here.</p><button onClick={() => setView("explore")}>Explore titles</button></div>}
          <div className="card-grid">{shown.map((title) => <TitleCard key={title.id} title={title} entry={savedById.get(title.id)} saving={savingId === title.id} signedIn={signedIn} authConfigured={authConfigured} onSave={save} />)}</div>
        </section>
      )}
      <footer className="footer">Movie and TV metadata from TMDB · Game metadata from IGDB</footer>
    </main>
  );
}

function DiscoverRail({ label, title, titles, loading, savedById, savingId, signedIn, authConfigured, onSave }: {
  label: string; title: string; titles: Title[]; loading: boolean; savedById: Map<string, Entry>;
  savingId: string | null; signedIn: boolean; authConfigured: boolean;
  onSave: (id: string, status: Status | "") => Promise<void>;
}) {
  return (
    <section className="discover-section">
      <div className="section-heading"><div><p className="eyebrow">{label}</p><h3>{title}</h3></div><span className="result-count">{titles.length ? `${titles.length} titles` : ""}</span></div>
      {loading && !titles.length && <p className="empty-state">Loading titles…</p>}
      {!loading && !titles.length && <p className="empty-state">No releases available right now.</p>}
      <div className="discover-rail">{titles.map((item) => <TitleCard key={item.id} title={item} entry={savedById.get(item.id)} saving={savingId === item.id} signedIn={signedIn} authConfigured={authConfigured} onSave={onSave} />)}</div>
    </section>
  );
}

function TitleCard({ title, entry, saving, signedIn, authConfigured, onSave }: {
  title: Title; entry?: Entry; saving: boolean; signedIn: boolean; authConfigured: boolean;
  onSave: (id: string, status: Status | "") => Promise<void>;
}) {
  const year = title.release_date?.slice(0, 4);
  return (
    <article className="title-card">
      <div className={`poster ${title.media_type}`}>
        {title.poster_url ? <img src={title.poster_url} alt="" loading="lazy" /> : <span aria-hidden="true">{title.name.slice(0, 1)}</span>}
        <span className="type-badge">{typeNames[title.media_type]}</span>
      </div>
      <div className="card-body">
        <div className="card-meta"><span>{year || "Date unknown"}</span><span>·</span><span>{title.provider.toUpperCase()}</span></div>
        <h3 title={title.name}>{title.name}</h3>
        {title.overview && <p className="description">{title.overview}</p>}
        {signedIn ? (
          <div className="card-actions"><label className="status-picker"><span className="sr-only">Tracking status for {title.name}</span><select disabled={saving} value={entry?.status || ""} onChange={(event) => void onSave(title.id, event.target.value as Status | "")}><option value="" disabled>Add to library</option>{statuses.map((status) => <option key={status.value} value={status.value}>{status.label}</option>)}</select><span aria-hidden="true">⌄</span></label>{entry && <button className="remove-entry" disabled={saving} onClick={() => void onSave(title.id, "")}>Remove</button>}</div>
        ) : (
          <span className="save-hint">{authConfigured ? "Sign in to save" : "Saving available after sign-in setup"}</span>
        )}
      </div>
    </article>
  );
}
