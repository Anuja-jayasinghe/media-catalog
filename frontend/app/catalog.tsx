"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type View = "discover" | "search" | "library";
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
type CatalogResponse = { results: Title[]; warnings: string[]; cached: boolean };
type DiscoverSection = "recent" | "upcoming";
type TokenGetter = () => Promise<string | null>;
type IconName = "mark" | "discover" | "search" | "library" | "sun" | "moon" | "close" | "left" | "right" | "arrow" | "check" | "plus";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const navigation: { value: View; label: string; icon: IconName }[] = [
  { value: "discover", label: "Discover", icon: "discover" },
  { value: "search", label: "Search", icon: "search" },
  { value: "library", label: "My library", icon: "library" },
];
const filters: { value: MediaType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "movie", label: "Movies" },
  { value: "tv", label: "TV series" },
  { value: "game", label: "Games" },
];
const statuses: { value: Status; label: string }[] = [
  { value: "planned", label: "Planned" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "dropped", label: "Dropped" },
];
const mediaNames = { movie: "Movie", tv: "TV series", game: "Game" };
const statusNames = { planned: "Planned", in_progress: "In progress", completed: "Completed", dropped: "Dropped" };

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const shared = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const };
  if (name === "mark") return <svg {...shared}><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><path d="M17 13v8m-4-4h8"/></svg>;
  if (name === "discover") return <svg {...shared}><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2.1 4.9-4.9 2.1 2.1-4.9z"/></svg>;
  if (name === "search") return <svg {...shared}><circle cx="10.8" cy="10.8" r="6.7"/><path d="m16 16 4.3 4.3"/></svg>;
  if (name === "library") return <svg {...shared}><path d="M5 4.5h14v15H5z"/><path d="M8 4.5v15M11 8h5M11 11h5"/></svg>;
  if (name === "sun") return <svg {...shared}><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>;
  if (name === "moon") return <svg {...shared}><path d="M20 15.4A8.5 8.5 0 0 1 8.6 4 8.5 8.5 0 1 0 20 15.4Z"/></svg>;
  if (name === "close") return <svg {...shared}><path d="M5 5l14 14M19 5 5 19"/></svg>;
  if (name === "left") return <svg {...shared}><path d="m15 5-7 7 7 7"/></svg>;
  if (name === "right") return <svg {...shared}><path d="m9 5 7 7-7 7"/></svg>;
  if (name === "arrow") return <svg {...shared}><path d="M4 12h16m-7-7 7 7-7 7"/></svg>;
  if (name === "check") return <svg {...shared}><path d="m4 12 5 5L20 6"/></svg>;
  return <svg {...shared}><path d="M12 4v16M4 12h16"/></svg>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

function yearOf(title: Title) { return title.release_date?.slice(0, 4) || "Date unknown"; }
function initialView(): View {
  if (typeof window === "undefined") return "discover";
  const value = new URLSearchParams(window.location.search).get("view");
  return value === "search" || value === "library" ? value : "discover";
}

export function SignedCatalog() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const tokenGetter = useCallback(() => getToken(), [getToken]);
  const authControl = !isLoaded ? <span className="account-loading">Loading…</span> : isSignedIn ? <UserButton /> : <SignInButton mode="modal"><button className="sign-in-button">Sign in</button></SignInButton>;
  return <Catalog signedIn={Boolean(isSignedIn)} authConfigured tokenGetter={tokenGetter} authControl={authControl} />;
}

export function GuestCatalog() {
  return <Catalog signedIn={false} authConfigured={false} authControl={<span className="guest-label">Preview mode</span>} />;
}

function Catalog({ signedIn, authConfigured, tokenGetter, authControl }: {
  signedIn: boolean;
  authConfigured: boolean;
  tokenGetter?: TokenGetter;
  authControl: React.ReactNode;
}) {
  const [view, setView] = useState<View>("discover");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MediaType>("all");
  const [libraryFilter, setLibraryFilter] = useState<Status | "all">("all");
  const [results, setResults] = useState<Title[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchWarning, setSearchWarning] = useState("");
  const [searchRetry, setSearchRetry] = useState(0);
  const [visibleCount, setVisibleCount] = useState(12);
  const [discover, setDiscover] = useState<Record<DiscoverSection, Title[]>>({ recent: [], upcoming: [] });
  const [discoverLoading, setDiscoverLoading] = useState(true);
  const [discoverError, setDiscoverError] = useState("");
  const [discoverRetry, setDiscoverRetry] = useState(0);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [selectedTitle, setSelectedTitle] = useState<Title | null>(null);
  const [toast, setToast] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const savedById = useMemo(() => new Map(entries.map((entry) => [entry.title.id, entry])), [entries]);
  const filteredEntries = entries.filter((entry) => libraryFilter === "all" || entry.status === libraryFilter);

  useEffect(() => {
    setView(initialView());
    const saved = window.localStorage.getItem("media-catalog-theme");
    if (saved === "light" || saved === "dark") setTheme(saved);
    const onPopState = () => setView(initialView());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (view === "search") requestAnimationFrame(() => searchRef.current?.focus());
  }, [view]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function navigate(next: View) {
    if (next === view) return;
    const url = new URL(window.location.href);
    if (next === "discover") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    window.history.pushState({ view: next }, "", url);
    setView(next);
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  function changeTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    window.localStorage.setItem("media-catalog-theme", next);
  }

  const loadLibrary = useCallback(async () => {
    if (!signedIn || !tokenGetter) {
      setEntries([]);
      return;
    }
    setLibraryLoading(true);
    setLibraryError("");
    try {
      const token = await tokenGetter();
      if (!token) throw new Error("Your session is not ready. Please sign in again.");
      const response = await fetch(`${apiBase}/api/library`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (!response.ok) throw new Error(await errorMessage(response));
      setEntries(await response.json());
    } catch (cause) {
      setLibraryError(cause instanceof Error ? cause.message : "Could not load your library");
    } finally {
      setLibraryLoading(false);
    }
  }, [signedIn, tokenGetter]);

  useEffect(() => { void loadLibrary(); }, [loadLibrary]);

  useEffect(() => {
    const controller = new AbortController();
    setDiscover({ recent: [], upcoming: [] });
    setDiscoverLoading(true);
    setDiscoverError("");
    const load = async () => {
      const warnings: string[] = [];
      for (const section of ["recent", "upcoming"] as const) {
        try {
          const params = new URLSearchParams({ section, media_type: "all" });
          const response = await fetch(`${apiBase}/api/discover?${params}`, { signal: controller.signal });
          if (!response.ok) throw new Error(await errorMessage(response));
          const body: CatalogResponse = await response.json();
          if (!controller.signal.aborted) {
            setDiscover((current) => ({ ...current, [section]: body.results }));
            warnings.push(...body.warnings);
          }
        } catch (cause) {
          if (!controller.signal.aborted) warnings.push(cause instanceof Error ? cause.message : "Could not load releases");
        }
      }
      if (!controller.signal.aborted) {
        setDiscoverError([...new Set(warnings)].join(" · "));
        setDiscoverLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [discoverRetry]);

  useEffect(() => {
    const trimmed = query.trim();
    setVisibleCount(12);
    if (view !== "search" || trimmed.length < 2) {
      setResults([]);
      setSearching(false);
      setSearchError("");
      setSearchWarning("");
      return;
    }
    setSearching(true);
    setSearchError("");
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: trimmed, media_type: filter });
        const response = await fetch(`${apiBase}/api/search?${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error(await errorMessage(response));
        const body: CatalogResponse = await response.json();
        if (!controller.signal.aborted) {
          setResults(body.results);
          setSearchWarning(body.warnings.join(" · "));
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setResults([]);
          setSearchError(cause instanceof Error ? cause.message : "Search failed");
        }
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, 300);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [view, query, filter, searchRetry]);

  async function save(titleId: string, status: Status | ""): Promise<void> {
    if (!signedIn || !tokenGetter) return;
    setSavingId(titleId);
    setSaveError("");
    try {
      const token = await tokenGetter();
      if (!token) throw new Error("Your session is not ready. Please sign in again.");
      const response = await fetch(`${apiBase}/api/library/${titleId}`, {
        method: status ? "PUT" : "DELETE",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: status ? JSON.stringify({ status }) : undefined,
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      if (status) {
        const changed: Entry = await response.json();
        setEntries((current) => [changed, ...current.filter((entry) => entry.title.id !== titleId)]);
        setToast(`${changed.title.name} marked ${statusNames[status].toLowerCase()}`);
      } else {
        setEntries((current) => current.filter((entry) => entry.title.id !== titleId));
        setToast("Removed from your library");
      }
    } catch (cause) {
      setSaveError(cause instanceof Error ? cause.message : "Could not update this title");
    } finally {
      setSavingId(null);
    }
  }

  const featured = discover.recent.find((title) => title.poster_url) || discover.recent[0];
  const recentTitles = discover.recent.filter((title) => title.id !== featured?.id);
  return (
    <div className="app-shell" data-theme={theme}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="sidebar-top"><div className="identity"><span className="identity-mark"><Icon name="mark" size={24}/></span><span>Media Catalog</span></div><p className="sidebar-caption">A place for everything you watch and play.</p></div>
        <nav className="sidebar-nav" aria-label="Sections">{navigation.map((item) => <NavItem key={item.value} item={item} active={view === item.value} count={item.value === "library" && signedIn ? entries.length : undefined} onClick={() => navigate(item.value)} />)}</nav>
        <div className="sidebar-bottom"><p className="sidebar-note">A personal record, made to revisit.</p><div className="sidebar-controls"><ThemeButton theme={theme} onClick={changeTheme}/>{authControl}</div></div>
      </aside>

      <header className="mobile-header"><div className="identity"><span className="identity-mark"><Icon name="mark" size={21}/></span><span>Media Catalog</span></div><div className="mobile-actions"><ThemeButton theme={theme} onClick={changeTheme}/>{authControl}</div></header>

      <main className="main-content" id="main-content">
        {view === "discover" && <>
          <div className="page-intro discover-intro"><div><p className="overline">YOUR MEDIA SPACE</p><h1>Discover</h1><p>Find your way back to the stories you loved, and see what is new.</p></div><button className="desktop-search-button" onClick={() => navigate("search")} aria-label="Search movies, TV series, and games"><Icon name="search" size={20}/><span>Search movies, series, and games</span><Icon name="arrow" size={18}/></button></div>
          {discoverError && <div className="inline-notice" role="status"><span>{discoverError}</span><button onClick={() => setDiscoverRetry((value) => value + 1)}>Try again</button></div>}
          {featured ? <button className="featured-card" onClick={() => setSelectedTitle(featured)} aria-label={`View details for ${featured.name}`}><div className="featured-copy"><span className="feature-kicker">IN THE SPOTLIGHT · {mediaNames[featured.media_type]}</span><h2>{featured.name}</h2><p>{featured.overview || "Explore this title and add it to your personal library."}</p><span className="feature-link">View title <Icon name="arrow" size={18}/></span></div><Poster title={featured} className="featured-poster"/></button> : discoverLoading ? <div className="feature-skeleton" aria-label="Loading featured title"/> : null}
          <TitleRail heading="Recently released" subheading="A fresh page in the catalog" titles={recentTitles} loading={discoverLoading} onSelect={setSelectedTitle} savedById={savedById}/>
          <TitleRail heading="Coming soon" subheading="Titles on the horizon" titles={discover.upcoming} loading={discoverLoading} onSelect={setSelectedTitle} savedById={savedById}/>
          <p className="catalog-footnote">Browse for inspiration. Your library is for what you actually watched or played.</p>
        </>}

        {view === "search" && <>
          <div className="page-intro"><p className="overline">ONE SEARCH, THREE WORLDS</p><h1>Find a title</h1><p>Search movies, TV series, and games together.</p></div>
          <div className="search-panel"><label htmlFor="catalog-search" className="field-label">Search the catalog</label><div className="search-field"><Icon name="search" size={22}/><input id="catalog-search" ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Title, sequel, or series" autoComplete="off" maxLength={120} type="search"/>{query && <button className="icon-button clear-button" onClick={() => { setQuery(""); searchRef.current?.focus(); }} aria-label="Clear search"><Icon name="close" size={18}/></button>}</div><div className="filter-group" role="group" aria-label="Filter search results by media type">{filters.map((item) => <button key={item.value} className={filter === item.value ? "filter-chip active" : "filter-chip"} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>)}</div></div>
          {query.trim().length < 2 ? <div className="search-start"><span className="search-start-icon"><Icon name="search" size={28}/></span><h2>{query.trim().length === 1 ? "Keep typing" : "What are you looking for?"}</h2><p>{query.trim().length === 1 ? "Enter at least two characters to search." : "Search across all three catalogs. You can narrow the results at any time."}</p></div> : <section className="results-section"><div className="section-heading"><div><p className="section-eyebrow">CATALOG RESULTS</p><h2>Results for “{query.trim()}”</h2></div><span className="section-count" role="status" aria-live="polite">{searching ? "Searching…" : `${results.length} titles`}</span></div>{searchWarning && <div className="inline-notice" role="status">{searchWarning}</div>}{searchError && <div className="inline-notice error" role="alert"><span>{searchError}</span><button onClick={() => setSearchRetry((value) => value + 1)}>Try again</button></div>}{searching ? <SkeletonGrid/> : results.length ? <div className="poster-grid">{results.slice(0, visibleCount).map((title) => <TitleTile key={title.id} title={title} entry={savedById.get(title.id)} onSelect={setSelectedTitle}/>)}</div> : !searchError && <div className="empty-state"><h3>No titles found</h3><p>Try another spelling or a different filter.</p></div>}{results.length > visibleCount && !searching && <button className="more-button" onClick={() => setVisibleCount((count) => count + 12)}>Show more titles</button>}</section>}
        </>}

        {view === "library" && <>
          <div className="page-intro"><p className="overline">YOUR PRIVATE COLLECTION</p><h1>My library</h1><p>Keep track of what you plan, finish, or leave behind.</p></div>
          {!signedIn ? <div className="library-gate"><span className="gate-icon"><Icon name="library" size={30}/></span><h2>Your library lives here</h2><p>{authConfigured ? "Sign in to start tracking movies, series, and games in one private place." : "Sign-in setup is coming later. You can explore the catalog now."}</p><button className="primary-button" onClick={() => navigate("search")}>Browse titles <Icon name="arrow" size={18}/></button></div> : <>{libraryError && <div className="inline-notice error" role="alert"><span>{libraryError}</span><button onClick={() => void loadLibrary()}>Try again</button></div>}<div className="library-toolbar"><div className="filter-group" role="group" aria-label="Filter library by status"><button className={libraryFilter === "all" ? "filter-chip active" : "filter-chip"} aria-pressed={libraryFilter === "all"} onClick={() => setLibraryFilter("all")}>All <span>{entries.length}</span></button>{statuses.map((item) => <button key={item.value} className={libraryFilter === item.value ? "filter-chip active" : "filter-chip"} aria-pressed={libraryFilter === item.value} onClick={() => setLibraryFilter(item.value)}>{item.label}</button>)}</div></div>{libraryLoading ? <SkeletonGrid/> : filteredEntries.length ? <div className="poster-grid">{filteredEntries.map((entry) => <TitleTile key={entry.title.id} title={entry.title} entry={entry} onSelect={setSelectedTitle}/>)}</div> : <div className="empty-state"><h2>{entries.length ? "Nothing in this group" : "Your library is ready"}</h2><p>{entries.length ? "Choose another status to see your titles." : "Find a title you know, then add it to your library."}</p><button className="primary-button" onClick={() => navigate("search")}>Find a title <Icon name="arrow" size={18}/></button></div>}</>}
        </>}
        <footer className="site-footer">Movie and TV data from TMDB · Game data from IGDB</footer>
      </main>

      <nav className="bottom-nav" aria-label="Sections">{navigation.map((item) => <NavItem key={item.value} item={item} active={view === item.value} onClick={() => navigate(item.value)}/>)}</nav>
      <TitleDialog title={selectedTitle} entry={selectedTitle ? savedById.get(selectedTitle.id) : undefined} saving={selectedTitle?.id === savingId} error={saveError} signedIn={signedIn} authConfigured={authConfigured} onClose={() => { setSelectedTitle(null); setSaveError(""); }} onSave={save}/>
      {toast && <div className="toast" role="status"><Icon name="check" size={18}/>{toast}</div>}
    </div>
  );
}

function NavItem({ item, active, count, onClick }: { item: { value: View; label: string; icon: IconName }; active: boolean; count?: number; onClick: () => void }) {
  return <button className={active ? "nav-item active" : "nav-item"} aria-current={active ? "page" : undefined} onClick={onClick}><Icon name={item.icon} size={21}/><span>{item.label}</span>{count !== undefined && <span className="nav-count" aria-label={`${count} saved titles`}>{count}</span>}</button>;
}

function ThemeButton({ theme, onClick }: { theme: "dark" | "light"; onClick: () => void }) {
  return <button className="theme-button" onClick={onClick} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`} title={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`}><Icon name={theme === "dark" ? "sun" : "moon"} size={19}/></button>;
}

function Poster({ title, className = "" }: { title: Title; className?: string }) {
  return <div className={`poster-art ${className} poster-${title.media_type}`}>{title.poster_url ? <img src={title.poster_url} alt="" loading="lazy" decoding="async"/> : <span className="poster-fallback" aria-hidden="true">{title.name.slice(0, 1)}</span>}</div>;
}

function TitleTile({ title, entry, onSelect }: { title: Title; entry?: Entry; onSelect: (title: Title) => void }) {
  return <article className="title-tile"><button onClick={() => onSelect(title)} aria-label={`View details for ${title.name}, ${mediaNames[title.media_type]}, ${yearOf(title)}`}><div className="tile-image"><Poster title={title}/>{entry && <span className="tile-status"><Icon name="check" size={13}/>{statusNames[entry.status]}</span>}</div><span className="tile-type">{mediaNames[title.media_type]} · {yearOf(title)}</span><span className="tile-title">{title.name}</span></button></article>;
}

function TitleRail({ heading, subheading, titles, loading, onSelect, savedById }: { heading: string; subheading: string; titles: Title[]; loading: boolean; onSelect: (title: Title) => void; savedById: Map<string, Entry> }) {
  const railRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const update = () => setEdges({ left: rail.scrollLeft > 2, right: rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 2 });
    update();
    rail.addEventListener("scroll", update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(rail);
    return () => { rail.removeEventListener("scroll", update); observer.disconnect(); };
  }, [titles.length]);
  function scroll(direction: -1 | 1) {
    const rail = railRef.current;
    if (!rail) return;
    rail.scrollBy({ left: direction * Math.max(rail.clientWidth * 0.8, 240), behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
  return <section className="title-section"><div className="section-heading"><div><p className="section-eyebrow">{subheading}</p><h2>{heading}</h2></div><div className="rail-controls"><button onClick={() => scroll(-1)} disabled={!edges.left} aria-label={`Scroll ${heading.toLowerCase()} left`}><Icon name="left" size={18}/></button><button onClick={() => scroll(1)} disabled={!edges.right} aria-label={`Scroll ${heading.toLowerCase()} right`}><Icon name="right" size={18}/></button></div></div>{loading && !titles.length ? <div className="title-rail" aria-label={`Loading ${heading.toLowerCase()}`}><SkeletonTile/><SkeletonTile/><SkeletonTile/><SkeletonTile/></div> : titles.length ? <div className="title-rail" ref={railRef}>{titles.map((title) => <TitleTile key={title.id} title={title} entry={savedById.get(title.id)} onSelect={onSelect}/>)}</div> : <div className="empty-state compact"><p>No titles available here right now.</p></div>}</section>;
}

function SkeletonTile() { return <div className="skeleton-tile"><div className="skeleton-poster"/><div className="skeleton-line short"/><div className="skeleton-line"/></div>; }
function SkeletonGrid() { return <div className="poster-grid" aria-label="Loading titles"><SkeletonTile/><SkeletonTile/><SkeletonTile/><SkeletonTile/><SkeletonTile/><SkeletonTile/></div>; }

function TitleDialog({ title, entry, saving, error, signedIn, authConfigured, onClose, onSave }: { title: Title | null; entry?: Entry; saving: boolean; error: string; signedIn: boolean; authConfigured: boolean; onClose: () => void; onSave: (id: string, status: Status | "") => Promise<void> }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (title && !dialog.open) {
      dialog.showModal();
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = previousOverflow; };
    }
    if (!title && dialog.open) dialog.close();
  }, [title]);
  return <dialog ref={dialogRef} className="title-dialog" onClose={onClose} onClick={(event) => { if (event.target === dialogRef.current) dialogRef.current?.close(); }} aria-label={title ? `Details for ${title.name}` : "Title details"}>{title && <div className="dialog-inner"><div className="dialog-art"><Poster title={title}/></div><div className="dialog-content"><button className="dialog-close" onClick={() => dialogRef.current?.close()} aria-label="Close title details"><Icon name="close" size={20}/></button><p className="dialog-kicker">{mediaNames[title.media_type]} · {yearOf(title)} · {title.provider.toUpperCase()}</p><h2>{title.name}</h2><p className="dialog-description">{title.overview || "No description is available for this title yet."}</p><div className="tracking-panel"><div className="tracking-heading"><h3>Track this title</h3>{entry && <span className="current-status"><Icon name="check" size={15}/>{statusNames[entry.status]}</span>}</div>{signedIn ? <><p>Choose where this title belongs in your library.</p><div className="status-options">{statuses.map((item) => <button key={item.value} className={entry?.status === item.value ? "status-option selected" : "status-option"} aria-pressed={entry?.status === item.value} disabled={saving} onClick={() => void onSave(title.id, item.value)}>{entry?.status === item.value ? <Icon name="check" size={17}/> : <Icon name="plus" size={17}/>}<span>{item.label}</span></button>)}</div>{entry && <button className="remove-button" disabled={saving} onClick={() => void onSave(title.id, "")}>Remove from my library</button>}{saving && <p className="save-feedback" role="status">Saving your change…</p>}</> : <p>{authConfigured ? "Sign in to save this title to your private library." : "Saving will be available when sign-in is set up. You can still explore the catalog."}</p>}{error && <p className="dialog-error" role="alert">{error}</p>}</div></div></div>}</dialog>;
}
