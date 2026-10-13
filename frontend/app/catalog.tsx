"use client";

import { SignInButton, SignUpButton, UserButton, useAuth, useClerk } from "@clerk/nextjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Kind = "movie" | "tv" | "game";
type View = "home" | Kind | "search" | "library";
type Section = "popular" | "recent" | "upcoming";
type Status = "planned" | "in_progress" | "completed" | "dropped";
type Title = { id: string; media_type: Kind; provider: string; provider_id: string; verified?: boolean; name: string; overview: string; poster_url: string | null; release_date: string | null };
type Entry = { title: Title; status: Status; completed_on: string | null; date_precision: string; rating_half_steps: number | null; review: string | null; favorite: boolean; platforms: string[]; lists: string[]; updated_at: string };
type EntryDetails = Pick<Entry, "completed_on" | "date_precision" | "rating_half_steps" | "review" | "favorite" | "platforms" | "lists">;
type CatalogResponse = { results: Title[]; warnings: string[]; has_more?: boolean };
type Media = { trailer_url: string | null; external_url: string; external_label: string };
type TvSeason = { number: number; name: string; episode_count: number | null; marked_at: string | null; through_episode: number | null };
type TvEpisode = { number: number; name: string; air_date: string | null; watched: boolean };
type ImportBatchSummary = { id: string; source: string; created_at: string; reverted_at: string | null; changes: number };
type ImportChangeSummary = { id: string; kind: string; title: string | null; reverted_at: string | null };
type MissingReportResult = { status: "found" | "choices" | "reported"; title: Title | null; choices: Title[]; report_id: string | null };
const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const kinds: { id: Kind; label: string; eyebrow: string; description: string }[] = [
  { id: "movie", label: "Movies", eyebrow: "THE BIG SCREEN", description: "A world of films, one discovery at a time." },
  { id: "tv", label: "TV series", eyebrow: "ONE MORE EPISODE", description: "Find a series worth staying up for." },
  { id: "game", label: "Games", eyebrow: "YOUR NEXT WORLD", description: "Discover worlds to play and remember." },
];
const statusLabel: Record<Status, string> = { planned: "Planned", in_progress: "In progress", completed: "Completed", dropped: "Dropped" };
const sections: { id: Section; label: string }[] = [{ id: "popular", label: "Popular" }, { id: "recent", label: "New releases" }, { id: "upcoming", label: "Coming soon" }];
function Icon({ name, size = 20 }: { name: "search" | "arrow" | "play" | "plus" | "check" | "close" | "left" | "right"; size?: number }) { const p = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const }; if (name === "search") return <svg {...p}><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.3 4.3"/></svg>; if (name === "arrow") return <svg {...p}><path d="M4 12h16m-7-7 7 7-7 7"/></svg>; if (name === "play") return <svg {...p} fill="currentColor" stroke="none"><path d="m8 4 12 8-12 8z"/></svg>; if (name === "plus") return <svg {...p}><path d="M12 4v16M4 12h16"/></svg>; if (name === "check") return <svg {...p}><path d="m4 12 5 5L20 6"/></svg>; if (name === "close") return <svg {...p}><path d="M5 5l14 14M19 5 5 19"/></svg>; if (name === "left") return <svg {...p}><path d="m15 5-7 7 7 7"/></svg>; return <svg {...p}><path d="m9 5 7 7-7 7"/></svg>; }
function label(kind: Kind) { return kinds.find((item) => item.id === kind)?.label || kind; }
function year(title: Title) { return title.release_date?.slice(0, 4) || "Date unknown"; }
function initialView(): View { if (typeof window === "undefined") return "home"; const v = new URLSearchParams(window.location.search).get("view"); return v === "movie" || v === "tv" || v === "game" || v === "search" || v === "library" ? v : "home"; }
function href(view: View) { return view === "home" ? "/" : `/?view=${view}`; }
async function errorText(response: Response) { try { const body = await response.json(); if (typeof body.detail === "string") return body.detail; if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg; return `Request failed (${response.status})`; } catch { return `Request failed (${response.status})`; } }
function providerUrl(title: Title) { if (title.provider === "tvmaze") return `https://www.tvmaze.com/shows/${title.provider_id}`; if (title.provider === "rawg") return `https://rawg.io/games/${title.provider_id}`; return title.media_type === "game" ? `https://www.igdb.com/games/${title.provider_id}` : `https://www.themoviedb.org/${title.media_type}/${title.provider_id}`; }

export function SignedCatalog() { const { isLoaded, isSignedIn, getToken } = useAuth(); const clerk = useClerk(); const token = useCallback(() => getToken(), [getToken]); const auth = !isLoaded ? <span className="auth-note">Loading…</span> : isSignedIn ? <UserButton/> : <SignInButton mode="modal"><button className="sign-in-link">Sign in</button></SignInButton>; const signup = isLoaded && !isSignedIn ? <SignUpButton mode="modal"><button className="library-sign-up">Create account</button></SignUpButton> : null; return <Catalog signedIn={Boolean(isSignedIn)} authConfigured getToken={token} onDeleted={() => clerk.signOut()} auth={auth} signup={signup}/>; }
export function GuestCatalog() { return <Catalog signedIn={false} authConfigured={false} auth={null}/>; }
function Catalog({ signedIn, authConfigured, getToken, onDeleted, auth, signup }: { signedIn: boolean; authConfigured: boolean; getToken?: () => Promise<string | null>; onDeleted?: () => Promise<void>; auth: React.ReactNode; signup?: React.ReactNode }) {
  const [view, setView] = useState<View>("home");
  const [home, setHome] = useState<Record<string, Title[]>>({}); const [homeLoading, setHomeLoading] = useState(true); const [homeError, setHomeError] = useState(""); const [homeRetry, setHomeRetry] = useState(0);
  const [section, setSection] = useState<Section>("popular"); const [page, setPage] = useState(1); const [catalog, setCatalog] = useState<Title[]>([]); const [catalogLoading, setCatalogLoading] = useState(false); const [hasMore, setHasMore] = useState(true); const [catalogError, setCatalogError] = useState(""); const [catalogRetry, setCatalogRetry] = useState(0);
  const [query, setQuery] = useState(""); const [searchKind, setSearchKind] = useState<Kind | "all">("all"); const [results, setResults] = useState<Title[]>([]); const [searching, setSearching] = useState(false); const [searchError, setSearchError] = useState(""); const [searchRetry, setSearchRetry] = useState(0);
  const [entries, setEntries] = useState<Entry[]>([]); const [libraryLoading, setLibraryLoading] = useState(false); const [libraryError, setLibraryError] = useState(""); const [libraryStatus, setLibraryStatus] = useState<Status | "all">("all");
  const [selected, setSelected] = useState<Title | null>(null); const [media, setMedia] = useState<Media | null>(null); const [mediaLoading, setMediaLoading] = useState(false); const [saveError, setSaveError] = useState(""); const [savingId, setSavingId] = useState<string | null>(null); const [toast, setToast] = useState("");
  const [reportDraft, setReportDraft] = useState<{ name: string; kind: Kind | "" } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null); const sentinel = useRef<HTMLDivElement>(null); const mediaRequest = useRef(0);
  const saved = useMemo(() => new Map(entries.map((entry) => [entry.title.id, entry])), [entries]);
  useEffect(() => { setView(initialView()); const pop = () => setView(initialView()); window.addEventListener("popstate", pop); return () => window.removeEventListener("popstate", pop); }, []);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("title");
    if (!id) return;
    const controller = new AbortController();
    void fetch(`${base}/api/titles/${encodeURIComponent(id)}`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<Title> : null)
      .then((title) => { if (title && !controller.signal.aborted) track(title); })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  useEffect(() => { if (view === "search") requestAnimationFrame(() => searchRef.current?.focus()); }, [view]);
  useEffect(() => { if (!toast) return; const id = window.setTimeout(() => setToast(""), 3200); return () => window.clearTimeout(id); }, [toast]);
  function navigate(next: View) { if (next === view) return; window.history.pushState({}, "", href(next)); setView(next); window.scrollTo({ top: 0, behavior: "auto" }); }
  function link(event: React.MouseEvent<HTMLAnchorElement>, next: View) { event.preventDefault(); navigate(next); }
  const loadLibrary = useCallback(async () => { if (!signedIn || !getToken) { setEntries([]); return; } setLibraryLoading(true); setLibraryError(""); try { const token = await getToken(); if (!token) throw new Error("Your session is not ready. Please sign in again."); const response = await fetch(`${base}/api/library`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }); if (!response.ok) throw new Error(await errorText(response)); setEntries(await response.json()); } catch (error) { setLibraryError(error instanceof Error ? error.message : "Could not load your library"); } finally { setLibraryLoading(false); } }, [signedIn, getToken]);
  useEffect(() => { void loadLibrary(); }, [loadLibrary]);
  useEffect(() => { const controller = new AbortController(); setHomeLoading(true); setHomeError(""); const requests = kinds.flatMap((kind) => (["recent", "upcoming"] as const).map(async (s) => { const params = new URLSearchParams({ section: s, media_type: kind.id }); const response = await fetch(`${base}/api/discover?${params}`, { signal: controller.signal }); if (!response.ok) throw new Error(await errorText(response)); return { key: `${kind.id}:${s}`, body: await response.json() as CatalogResponse }; })); void Promise.allSettled(requests).then((outcomes) => { if (controller.signal.aborted) return; const next: Record<string, Title[]> = {}; const issues: string[] = []; for (const result of outcomes) { if (result.status === "fulfilled") { next[result.value.key] = result.value.body.results; issues.push(...result.value.body.warnings); } else issues.push("Some titles could not be loaded"); } setHome(next); setHomeError([...new Set(issues)].join(" · ")); setHomeLoading(false); }); return () => controller.abort(); }, [homeRetry]);
  useEffect(() => { setCatalog([]); setPage(1); setHasMore(true); setCatalogError(""); }, [view, section]);
  useEffect(() => { if (view !== "movie" && view !== "tv" && view !== "game") return; const controller = new AbortController(); setCatalogLoading(true); setCatalogError(""); const params = new URLSearchParams({ section, media_type: view, page: String(page) }); void (async () => { try { const response = await fetch(`${base}/api/discover?${params}`, { signal: controller.signal }); if (!response.ok) throw new Error(await errorText(response)); const body: CatalogResponse = await response.json(); if (controller.signal.aborted) return; setCatalog((current) => page === 1 ? body.results : [...current, ...body.results.filter((item) => !current.some((old) => old.id === item.id))]); setHasMore(Boolean(body.has_more) && page < 500); if (body.warnings.length) setCatalogError(body.warnings.join(" · ")); } catch (error) { if (!controller.signal.aborted) setCatalogError(error instanceof Error ? error.message : "Could not load titles"); } finally { if (!controller.signal.aborted) setCatalogLoading(false); } })(); return () => controller.abort(); }, [view, section, page, catalogRetry]);
  useEffect(() => { const node = sentinel.current; if (!node || !hasMore || catalogLoading || catalogError) return; const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) setPage((n) => n + 1); }, { rootMargin: "650px" }); observer.observe(node); return () => observer.disconnect(); }, [view, hasMore, catalogLoading, catalogError, catalog.length]);
  useEffect(() => { const term = query.trim(); if (view !== "search" || term.length < 2) { setResults([]); setSearching(false); setSearchError(""); return; } const controller = new AbortController(); setSearching(true); setSearchError(""); const timer = window.setTimeout(async () => { try { const params = new URLSearchParams({ q: term, media_type: searchKind }); const response = await fetch(`${base}/api/search?${params}`, { signal: controller.signal }); if (!response.ok) throw new Error(await errorText(response)); const body: CatalogResponse = await response.json(); if (!controller.signal.aborted) setResults(body.results); } catch (error) { if (!controller.signal.aborted) { setResults([]); setSearchError(error instanceof Error ? error.message : "Search failed"); } } finally { if (!controller.signal.aborted) setSearching(false); } }, 250); return () => { controller.abort(); window.clearTimeout(timer); }; }, [view, query, searchKind, searchRetry]);
  async function open(title: Title) { const id = ++mediaRequest.current; setSelected(title); setMedia(null); setMediaLoading(true); setSaveError(""); try { const response = await fetch(`${base}/api/titles/${title.id}/media`); if (!response.ok) throw new Error(await errorText(response)); const detail: Media = await response.json(); if (id !== mediaRequest.current) return; if (detail.trailer_url) { setMedia(detail); setMediaLoading(false); } else window.location.assign(detail.external_url); } catch { if (id === mediaRequest.current) window.location.assign(providerUrl(title)); } }
  function track(title: Title) { ++mediaRequest.current; setSelected(title); setMedia(null); setMediaLoading(false); setSaveError(""); }
  function close() { ++mediaRequest.current; setSelected(null); setMedia(null); setMediaLoading(false); setSaveError(""); }
  function reportFound(title: Title) { setQuery(title.name); setSearchKind(title.media_type); setResults([title]); setToast(`${title.name} is already in the catalog`); setReportDraft(null); }
  async function save(titleId: string, status: Status | "", details?: EntryDetails) { if (!signedIn || !getToken) return; setSavingId(titleId); setSaveError(""); try { const token = await getToken(); if (!token) throw new Error("Your session is not ready. Please sign in again."); const response = await fetch(`${base}/api/library/${titleId}`, { method: status ? "PUT" : "DELETE", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: status ? JSON.stringify({ status, ...details }) : undefined }); if (!response.ok) throw new Error(await errorText(response)); if (status) { const changed: Entry = await response.json(); setEntries((items) => [changed, ...items.filter((item) => item.title.id !== titleId)]); setToast(`${changed.title.name} · Saved`); } else { setEntries((items) => items.filter((item) => item.title.id !== titleId)); setToast("Removed from your library"); } } catch (error) { setSaveError(error instanceof Error ? error.message : "Could not update this title"); } finally { setSavingId(null); } }
  const featured = home["movie:recent"]?.find((item) => item.poster_url) || home["movie:recent"]?.[0] || home["tv:recent"]?.[0];
  const current = kinds.find((item) => item.id === view);
  const categoryHero = catalog.find((item) => item.poster_url) || catalog[0];
  const filtered = entries.filter((entry) => libraryStatus === "all" || entry.status === libraryStatus);
  return <div className="site-shell"><a className="skip-link" href="#main-content">Skip to content</a><header className="site-header"><a className="wordmark" href="/" onClick={(event) => link(event, "home")} aria-label="MTGL home"><span className="wordmark-symbol">M<span>.</span></span><span>MTGL</span></a><nav className="top-links" aria-label="Explore"><a href={href("home")} aria-current={view === "home" ? "page" : undefined} onClick={(event) => link(event, "home")}>Home</a>{kinds.map((item) => <a key={item.id} href={href(item.id)} aria-current={view === item.id ? "page" : undefined} onClick={(event) => link(event, item.id)}>{item.label}</a>)}<a href={href("library")} aria-current={view === "library" ? "page" : undefined} onClick={(event) => link(event, "library")}>My library</a></nav><div className="header-actions"><a className="header-search" href={href("search")} onClick={(event) => link(event, "search")} aria-label="Search the catalog"><Icon name="search" size={22}/><span>Search</span></a>{auth}</div></header>
  <main id="main-content">{view === "home" && <><Hero title={featured} loading={homeLoading} onOpen={open} onTrack={track} onBrowse={() => navigate("movie")}/><div className="content-wrap home-content">{homeError && <Notice text={homeError} onRetry={() => setHomeRetry((n) => n + 1)}/ >}{kinds.map((kind) => <section className="home-world" key={kind.id} aria-labelledby={`home-${kind.id}`}><div className="world-heading"><div><p className="eyebrow">{kind.eyebrow}</p><h2 id={`home-${kind.id}`}>{kind.label}</h2></div><a href={href(kind.id)} onClick={(event) => link(event, kind.id)}>Explore all <Icon name="arrow" size={18}/></a></div><TitleRail heading="Just released" titles={home[`${kind.id}:recent`] || []} loading={homeLoading} onOpen={open} onTrack={track} saved={saved}/><TitleRail heading="On the horizon" titles={home[`${kind.id}:upcoming`] || []} loading={homeLoading} onOpen={open} onTrack={track} saved={saved}/></section>)}</div></>}
  {current && <><div className="category-banner" style={categoryHero?.poster_url ? { backgroundImage: `linear-gradient(90deg,#08090d 6%,rgba(8,9,13,.92) 42%,rgba(8,9,13,.62) 100%),url('${categoryHero.poster_url}')` } : undefined}><div className="content-wrap category-banner-inner"><p className="eyebrow">{current.eyebrow}</p><h1>{current.label}</h1><p>{current.description}</p></div></div><div className="content-wrap category-content"><div className="category-toolbar"><div className="tab-list" role="group" aria-label={`Browse ${current.label.toLowerCase()}`}>{sections.map((item) => <button key={item.id} className={section === item.id ? "browse-tab active" : "browse-tab"} aria-pressed={section === item.id} onClick={() => { setSection(item.id); window.scrollTo({ top: 0, behavior: "auto" }); }}>{item.label}</button>)}</div><span className="browse-count" aria-live="polite">{catalog.length ? `${catalog.length} titles` : catalogLoading ? "Loading…" : ""}</span></div>{catalogError && <Notice text={catalogError} onRetry={() => setCatalogRetry((n) => n + 1)}/ >}{catalog.length ? <div className="poster-grid">{catalog.map((title) => <TitleCard key={title.id} title={title} entry={saved.get(title.id)} onOpen={open} onTrack={track}/>)}</div> : catalogLoading ? <SkeletonGrid/> : !catalogError && <EmptyState title="Nothing here yet" text="Try another collection or check back soon."/>}{catalogLoading && catalog.length > 0 && <div className="load-status" role="status">Loading more titles…</div>}{hasMore && !catalogError && <div ref={sentinel} className="scroll-sentinel"><button onClick={() => setPage((n) => n + 1)} disabled={catalogLoading}>Load more {current.label.toLowerCase()}</button></div>}{!hasMore && catalog.length > 0 && <p className="end-note">You’ve reached the end of this collection.</p>}</div></>}
  {view === "search" && <div className="content-wrap inner-page search-page">
    <p className="eyebrow">EXPLORE THE CATALOG</p><h1>Find your next story.</h1>
    <p className="page-subtitle">Search once. Explore movies, series, and games in their own spaces.</p>
    <div className="search-box"><Icon name="search" size={25}/><input ref={searchRef} type="search" aria-label="Search titles" placeholder="Search a title…" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={120} autoComplete="off"/>{query && <button onClick={() => { setQuery(""); searchRef.current?.focus(); }} aria-label="Clear search"><Icon name="close" size={19}/></button>}</div>
    <div className="tab-list search-filters" role="group" aria-label="Filter search results">{[{ id: "all", label: "All" }, ...kinds].map((item) => <button key={item.id} className={searchKind === item.id ? "browse-tab active" : "browse-tab"} aria-pressed={searchKind === item.id} onClick={() => setSearchKind(item.id as Kind | "all")}>{item.label}</button>)}</div>
    {query.trim().length < 2 ? <EmptyState title="A title is all it takes" text="Start typing to search the catalog."/> : <>
      <div className="search-summary" role="status">{searching ? "Searching…" : `${results.length} results for “${query.trim()}”`}</div>
      {searchError && <Notice text={searchError} onRetry={() => setSearchRetry((n) => n + 1)}/>}
      {searching ? <SkeletonGrid/> : results.length ? kinds.filter((kind) => searchKind === "all" || searchKind === kind.id).map((kind) => {
        const group = results.filter((title) => title.media_type === kind.id);
        return group.length ? <section className="result-group" key={kind.id}><h2>{kind.label}</h2><div className="poster-grid">{group.map((title) => <TitleCard key={title.id} title={title} entry={saved.get(title.id)} onOpen={open} onTrack={track}/>)}</div></section> : null;
      }) : !searchError && <EmptyState title="No matches found" text="Try another spelling or change the filter."/>}
    </>}
    <div className="missing-prompt"><div><span className="eyebrow">STILL LOOKING?</span><h2>Can’t find a title?</h2><p>Tell us its name and we’ll check other sources, then add it to the shared catalog.</p></div><button onClick={() => setReportDraft({ name: query.trim(), kind: searchKind === "all" ? "" : searchKind })}>Report a missing title <Icon name="arrow" size={17}/></button></div>
  </div>}
  {view === "library" && <div className="content-wrap inner-page library-page"><p className="eyebrow">YOUR COLLECTION</p><h1>My library</h1><p className="page-subtitle">The movies, series, and games you want to remember.</p>{!signedIn ? <div className="library-gate"><h2>Your story starts here.</h2><p>{authConfigured ? "Create an account or sign in to keep a private record of what you watch and play." : "Account setup is coming later. Explore the catalog for now."}</p><div className="library-gate-actions">{signup}<a href={href("movie")} onClick={(event) => link(event, "movie")}>Explore movies <Icon name="arrow" size={18}/></a></div></div> : <>{libraryError && <Notice text={libraryError} onRetry={() => void loadLibrary()}/ >}<div className="tab-list library-filters" role="group" aria-label="Filter library by status"><button className={libraryStatus === "all" ? "browse-tab active" : "browse-tab"} aria-pressed={libraryStatus === "all"} onClick={() => setLibraryStatus("all")}>All</button>{(Object.keys(statusLabel) as Status[]).map((status) => <button key={status} className={libraryStatus === status ? "browse-tab active" : "browse-tab"} aria-pressed={libraryStatus === status} onClick={() => setLibraryStatus(status)}>{statusLabel[status]}</button>)}</div>{libraryLoading ? <SkeletonGrid/> : filtered.length ? kinds.map((kind) => { const group = filtered.filter((entry) => entry.title.media_type === kind.id); return group.length ? <section className="result-group" key={kind.id}><h2>{kind.label}</h2><div className="poster-grid">{group.map((entry) => <TitleCard key={entry.title.id} title={entry.title} entry={entry} onOpen={open} onTrack={track}/>)}</div></section> : null; }) : <EmptyState title={entries.length ? "Nothing in this group" : "Your library is ready"} text={entries.length ? "Choose another status to see your titles." : "Browse a collection and add a title you know."}/>}<AccountSettings getToken={getToken!} onImported={loadLibrary} onDeleted={onDeleted}/></>}</div>}</main>
  <footer className="site-footer content-wrap"><span>MTGL</span><span>Data from <a href="https://www.themoviedb.org/" target="_blank" rel="noopener noreferrer">TMDB</a> · <a href="https://www.igdb.com/" target="_blank" rel="noopener noreferrer">IGDB</a> · <a href="https://www.tvmaze.com/" target="_blank" rel="noopener noreferrer">TVmaze</a> · <a href="https://rawg.io/" target="_blank" rel="noopener noreferrer">RAWG</a></span></footer><MissingReportDialog draft={reportDraft} onClose={() => setReportDraft(null)} onFound={reportFound} onReported={() => { setReportDraft(null); setToast("Thanks — we’ll work on adding that title."); }}/><TitleDialog title={selected} media={media} loading={mediaLoading} entry={selected ? saved.get(selected.id) : undefined} saving={selected?.id === savingId} error={saveError} signedIn={signedIn} authConfigured={authConfigured} getToken={getToken} onUpdated={loadLibrary} onClose={close} onSave={save}/>{toast && <div className="toast" role="status"><Icon name="check" size={17}/>{toast}</div>}</div>;
}
function Poster({ title, eager = false }: { title: Title; eager?: boolean }) { return <div className={`poster-art poster-${title.media_type}`}>{title.poster_url ? <img src={title.poster_url} alt="" loading={eager ? "eager" : "lazy"} decoding="async"/> : <span aria-hidden="true">{title.name.slice(0, 1)}</span>}</div>; }
function TitleCard({ title, entry, onOpen, onTrack }: { title: Title; entry?: Entry; onOpen: (title: Title) => void; onTrack: (title: Title) => void }) { return <article className="title-card"><div className="card-art"><button className="card-open" onClick={() => onOpen(title)} aria-label={`View trailer or external page for ${title.name}`}><Poster title={title}/><span className="card-play"><Icon name="play" size={19}/></span></button><button className="card-add" onClick={() => onTrack(title)} aria-label={`${entry ? "Update" : "Add"} ${title.name} ${entry ? "in" : "to"} my library`} title={entry ? "Update in library" : "Add to library"}><Icon name={entry ? "check" : "plus"} size={20}/></button>{entry && <span className="card-status">{statusLabel[entry.status]}</span>}</div><div className="card-copy"><span>{year(title)}</span><h3>{title.name}</h3>{title.verified === false && <p className="provisional-note">Awaiting catalog match</p>}{entry && (entry.rating_half_steps || entry.favorite || entry.lists.length > 0) && <p className="card-personal">{entry.favorite && <span>Favorite</span>}{entry.rating_half_steps && <span>{(entry.rating_half_steps / 2).toFixed(1)} ★</span>}{entry.lists.map((name) => <span key={name}>{name}</span>)}</p>}</div></article>; }
function Hero({ title, loading, onOpen, onTrack, onBrowse }: { title?: Title; loading: boolean; onOpen: (title: Title) => void; onTrack: (title: Title) => void; onBrowse: () => void }) { return <section className="hero" aria-label="Featured title"><div className="hero-art" style={title?.poster_url ? { backgroundImage: `url('${title.poster_url}')` } : undefined}/><div className="hero-shade"/><div className="hero-content content-wrap"><p className="eyebrow">THE STORIES STAY WITH YOU</p>{loading && !title ? <><div className="hero-skeleton-title"/><div className="hero-skeleton-line"/></> : title ? <><p className="hero-pretitle">IN THE SPOTLIGHT · {label(title.media_type).toUpperCase()}</p><h1>{title.name}</h1><p className="hero-description">{title.overview || "A title worth discovering."}</p><div className="hero-actions"><button className="hero-primary" onClick={() => onOpen(title)}><Icon name="play" size={19}/> View title</button><button className="hero-secondary" onClick={() => onTrack(title)}><Icon name="plus" size={20}/> Add to library</button></div></> : <><h1>Every story deserves a place.</h1><p className="hero-description">Explore films, series, and games. Keep the ones that stay with you.</p><button className="hero-primary" onClick={onBrowse}>Explore movies <Icon name="arrow" size={19}/></button></>}</div><div className="hero-bottom"/></section>; }
function TitleRail({ heading, titles, loading, onOpen, onTrack, saved }: { heading: string; titles: Title[]; loading: boolean; onOpen: (title: Title) => void; onTrack: (title: Title) => void; saved: Map<string, Entry> }) { const ref = useRef<HTMLDivElement>(null); return <div className="rail-section"><div className="rail-heading"><h3>{heading}</h3><div className="rail-buttons"><button aria-label={`Scroll ${heading.toLowerCase()} left`} onClick={() => ref.current?.scrollBy({ left: -ref.current.clientWidth * .75, behavior: "smooth" })}><Icon name="left" size={19}/></button><button aria-label={`Scroll ${heading.toLowerCase()} right`} onClick={() => ref.current?.scrollBy({ left: ref.current.clientWidth * .75, behavior: "smooth" })}><Icon name="right" size={19}/></button></div></div>{loading && !titles.length ? <div className="title-rail"><SkeletonCard/><SkeletonCard/><SkeletonCard/><SkeletonCard/><SkeletonCard/></div> : titles.length ? <div className="title-rail" ref={ref}>{titles.map((title) => <TitleCard key={title.id} title={title} entry={saved.get(title.id)} onOpen={onOpen} onTrack={onTrack}/>)}</div> : <p className="quiet-note">Nothing to show here right now.</p>}</div>; }
function SkeletonCard() { return <div className="skeleton-card"><div/><span/><span/></div>; }
function SkeletonGrid() { return <div className="poster-grid" aria-label="Loading titles"><SkeletonCard/><SkeletonCard/><SkeletonCard/><SkeletonCard/><SkeletonCard/><SkeletonCard/></div>; }
function Notice({ text, onRetry }: { text: string; onRetry: () => void }) { return <div className="notice" role="alert"><span>{text}</span><button onClick={onRetry}>Try again</button></div>; }
function EmptyState({ title, text }: { title: string; text: string }) { return <div className="empty-state"><h2>{title}</h2><p>{text}</p></div>; }
function TitleDialog({ title, media, loading, entry, saving, error, signedIn, authConfigured, getToken, onUpdated, onClose, onSave }: { title: Title | null; media: Media | null; loading: boolean; entry?: Entry; saving: boolean; error: string; signedIn: boolean; authConfigured: boolean; getToken?: () => Promise<string | null>; onUpdated: () => Promise<void>; onClose: () => void; onSave: (id: string, status: Status | "", details?: EntryDetails) => Promise<void> }) { const ref = useRef<HTMLDialogElement>(null); useEffect(() => { const dialog = ref.current; if (!dialog) return; if (title && !dialog.open) dialog.showModal(); else if (!title && dialog.open) dialog.close(); }, [title]); return <dialog ref={ref} className="title-dialog" onClose={onClose} onClick={(event) => { if (event.target === ref.current) ref.current?.close(); }} aria-label={title ? `Details for ${title.name}` : "Title details"}>{title && <><button className="dialog-close" onClick={() => ref.current?.close()} aria-label="Close"><Icon name="close" size={21}/></button><div className="dialog-layout"><div className="dialog-visual">{media?.trailer_url ? <iframe src={`${media.trailer_url}?autoplay=1&rel=0`} title={`${title.name} trailer`} allow="autoplay; encrypted-media; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin"/> : <Poster title={title} eager/>}{loading && <div className="media-loading" role="status">Finding trailer…</div>}</div><div className="dialog-body"><p className="eyebrow">{label(title.media_type)} · {year(title)}</p><h2>{title.name}</h2><p className="dialog-overview">{title.overview || "No description is available for this title yet."}</p>{media && <a className="external-link" href={media.external_url} target="_blank" rel="noopener noreferrer">View on {media.external_label} <Icon name="arrow" size={17}/></a>}<div className="tracking-panel"><div className="tracking-heading"><h3>My library</h3>{entry && <span>{statusLabel[entry.status]}</span>}</div>{signedIn ? <><p>Choose how you want to remember this title.</p><div className="status-options">{(Object.keys(statusLabel) as Status[]).map((status) => <button key={status} className={entry?.status === status ? "status-option active" : "status-option"} aria-pressed={entry?.status === status} disabled={saving} onClick={() => void onSave(title.id, status)}><Icon name={entry?.status === status ? "check" : "plus"} size={17}/>{statusLabel[status]}</button>)}</div>{entry && <TrackingDetails key={`${title.id}:${entry.updated_at}`} title={title} entry={entry} saving={saving} onSave={onSave}/>} {title.media_type === "tv" && getToken && <TvProgress key={title.id} title={title} getToken={getToken} onUpdated={onUpdated}/>} {entry && <button className="remove-link" disabled={saving} onClick={() => void onSave(title.id, "")}>Remove from library</button>}{saving && <p role="status">Saving…</p>}</> : <p>{authConfigured ? "Sign in to save this title to your library." : "Saving will be available when account setup is complete."}</p>}{error && <p className="form-error" role="alert">{error}</p>}</div></div></div></>}</dialog>; }

function AccountSettings({ getToken, onImported, onDeleted }: { getToken: () => Promise<string | null>; onImported: () => Promise<void>; onDeleted?: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [shares, setShares] = useState<{ id: string; expires_at: string; revoked_at: string | null }[]>([]);
  const [days, setDays] = useState(7);
  const [newLink, setNewLink] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const [imports, setImports] = useState<ImportBatchSummary[]>([]);
  const [importChanges, setImportChanges] = useState<Record<string, ImportChangeSummary[]>>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    const token = await getToken(); if (!token) throw new Error("Please sign in again.");
    const response = await fetch(`${base}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init.headers } });
    if (!response.ok) throw new Error(await errorText(response));
    return response;
  }, [getToken]);
  useEffect(() => { let active = true; void Promise.all([request("/api/profile"), request("/api/shares"), request("/api/imports")]).then(async ([profile, links, batches]) => {
    const [info, items, recent] = await Promise.all([profile.json(), links.json(), batches.json()]);
    if (active) { setName(info.display_name); setShares(items); setImports(recent); }
  }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Could not load settings"); }); return () => { active = false; }; }, [request]);
  async function rename(event: React.FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(""); setMessage(""); try {
    const response = await request("/api/profile", { method: "PUT", body: JSON.stringify({ display_name: name.trim() }) });
    setName((await response.json()).display_name); setMessage("Display name saved.");
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save name"); } finally { setBusy(false); } }
  async function create() { setBusy(true); setError(""); setMessage(""); try {
    const response = await request("/api/shares", { method: "POST", body: JSON.stringify({ days }) });
    const item = await response.json();
    setShares((current) => [item, ...current]);
    setNewLink(`${window.location.origin}/share/${item.token}`);
    setMessage("Share link ready. Copy it before leaving this page.");
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create link"); } finally { setBusy(false); } }
  async function revoke(id: string) { setBusy(true); setError(""); try {
    await request(`/api/shares/${id}`, { method: "DELETE" });
    setShares((current) => current.map((item) => item.id === id ? { ...item, revoked_at: new Date().toISOString() } : item));
    setNewLink(""); setMessage("Link turned off.");
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not turn off link"); } finally { setBusy(false); } }
  async function download(kind: "backup" | "csv") { setBusy(true); setError(""); try {
    const response = await request(`/api/export/${kind}`);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url; link.download = kind === "backup" ? "mtgl-backup.json" : "mtgl.csv";
    document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not download export"); } finally { setBusy(false); } }
  async function refreshImports() {
    const response = await request("/api/imports");
    setImports(await response.json());
  }
  async function importBackup() { if (!importFile) return; setBusy(true); setError(""); setMessage(""); try {
    if (importFile.size > 20_000_000) throw new Error("Choose a backup smaller than 20 MB.");
    const parsed = JSON.parse(await importFile.text());
    const response = await request("/api/imports/backup", { method: "POST", body: JSON.stringify(parsed) });
    const result = await response.json();
    setMessage(`Restore complete: ${result.created} added, ${result.updated} updated${result.provisional ? `, ${result.provisional} awaiting source confirmation` : ""}. You can revert this import below.`);
    setImportFile(null); if (importInput.current) importInput.current.value = "";
    await Promise.all([onImported(), refreshImports()]);
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not restore backup"); } finally { setBusy(false); } }
  async function reviewImport(id: string) { setError(""); try {
    const response = await request(`/api/imports/${id}/changes`);
    const changes: ImportChangeSummary[] = await response.json();
    setImportChanges((current) => ({ ...current, [id]: changes }));
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load import changes"); } }
  async function revertImport(id: string, changeId?: string) { setBusy(true); setError(""); try {
    const suffix = changeId ? `/changes/${changeId}/revert` : "/revert";
    const response = await request(`/api/imports/${id}${suffix}`, { method: "POST" });
    const result = await response.json();
    setMessage(changeId ? "Selected change reverted." : `Reverted ${result.reverted} changes; ${result.skipped_changed_since_import} newer edits were kept.`);
    await Promise.all([onImported(), refreshImports()]);
    if (importChanges[id]) {
      const changes = await request(`/api/imports/${id}/changes`);
      const latest: ImportChangeSummary[] = await changes.json();
      setImportChanges((current) => ({ ...current, [id]: latest }));
    }
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not revert import"); } finally { setBusy(false); } }
  async function removeAccount() { setBusy(true); setError(""); try {
    await request("/api/account", { method: "DELETE" });
    if (onDeleted) await onDeleted();
    window.location.assign("/");
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not delete account"); setBusy(false); } }
  const activeShares = shares.filter((item) => !item.revoked_at && new Date(item.expires_at).getTime() > Date.now());
  return <details className="account-settings"><summary>Sharing & account settings</summary><div className="settings-content">
    <section><h2>Public name</h2><p>This name appears when you share your library. Your email stays private.</p><form className="settings-row" onSubmit={rename}><label className="sr-only" htmlFor="display-name">Public name</label><input id="display-name" value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={80} required/><button disabled={busy || !name.trim()}>Save name</button></form></section>
    <section><h2>Share your library</h2><p>A link shows your titles, statuses, ratings, and lists. Your notes stay private. Anyone with the link can view it until it expires.</p><div className="settings-row"><label className="sr-only" htmlFor="share-days">Link duration</label><select id="share-days" value={days} onChange={(event) => setDays(Number(event.target.value))}>{[1, 3, 7, 14].map((value) => <option key={value} value={value}>{value} {value === 1 ? "day" : "days"}</option>)}</select><button disabled={busy} onClick={() => void create()}>Create link</button></div>{newLink && <div className="share-created"><label>New link<input readOnly value={newLink} onFocus={(event) => event.target.select()}/></label><button onClick={() => void navigator.clipboard.writeText(newLink)}>Copy</button></div>}{activeShares.length > 0 && <div className="share-list"><h3>Active links</h3>{activeShares.map((item) => <div key={item.id}><span>Expires {new Date(item.expires_at).toLocaleDateString()}</span><button disabled={busy} onClick={() => void revoke(item.id)}>Turn off</button></div>)}</div>}</section>
    <section className="export-section"><h2>Export your library</h2><p>The native backup keeps every personal field and can be restored later. CSV is a portable table for other tools.</p><div className="export-actions"><button disabled={busy} onClick={() => void download("backup")}>Download full backup · JSON</button><button disabled={busy} onClick={() => void download("csv")}>Download table · CSV</button></div></section>
    <section className="import-section"><h2>Restore a backup</h2><p>Choose an MTGL JSON backup. We’ll keep titles from the file private until a catalog source confirms them.</p><label>Backup file<input ref={importInput} type="file" accept=".json,application/json" onChange={(event) => setImportFile(event.target.files?.[0] || null)}/></label><button disabled={busy || !importFile} onClick={() => void importBackup()}>{busy ? "Restoring…" : "Restore backup"}</button>{imports.length > 0 && <div className="import-history"><h3>Recent imports</h3>{imports.map((batch) => <div className="import-batch" key={batch.id}><div><span>{batch.source} · {new Date(batch.created_at).toLocaleDateString()} · {batch.reverted_at ? "Reverted" : `${batch.changes} active changes`}</span>{!batch.reverted_at && <div><button disabled={busy} onClick={() => void reviewImport(batch.id)}>Review changes</button><button disabled={busy} onClick={() => void revertImport(batch.id)}>Revert import</button></div>}</div>{importChanges[batch.id] && <ul>{importChanges[batch.id].map((change) => <li key={change.id}><span>{change.title || "Profile"} · {change.kind}</span>{change.reverted_at ? <small>Reverted</small> : <button disabled={busy} onClick={() => void revertImport(batch.id, change.id)}>Revert</button>}</li>)}</ul>}</div>)}</div>}</section>
    <section className="danger-section"><h2>Delete account</h2><p>This permanently removes your catalog, lists, share links, and sign-in account. Export your data first if you want a copy.</p>{confirmDelete ? <div className="settings-row"><button className="danger-button" disabled={busy} onClick={() => void removeAccount()}>{busy ? "Deleting…" : "Permanently delete account"}</button><button onClick={() => setConfirmDelete(false)}>Cancel</button></div> : <button className="danger-outline" onClick={() => setConfirmDelete(true)}>Delete my account…</button>}</section>
    {message && <p role="status">{message}</p>}{error && <p className="form-error" role="alert">{error}</p>}
  </div></details>;
}

function TvProgress({ title, getToken, onUpdated }: { title: Title; getToken: () => Promise<string | null>; onUpdated: () => Promise<void> }) {
  const [seasons, setSeasons] = useState<TvSeason[]>([]);
  const [seasonNumber, setSeasonNumber] = useState<number | null>(null);
  const [episodes, setEpisodes] = useState<TvEpisode[]>([]);
  const [through, setThrough] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const season = seasons.find((item) => item.number === seasonNumber);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => { try {
      const token = await getToken(); if (!token) throw new Error("Please sign in again.");
      const response = await fetch(`${base}/api/library/${title.id}/seasons`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
      if (!response.ok) throw new Error(await errorText(response));
      const found: TvSeason[] = await response.json();
      if (!controller.signal.aborted) { setSeasons(found); setSeasonNumber(found.find((item) => item.number > 0)?.number ?? found[0]?.number ?? null); }
    } catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load seasons"); }
    })();
    return () => controller.abort();
  }, [title.id, getToken]);
  useEffect(() => {
    if (seasonNumber === null) { setLoading(false); return; }
    const controller = new AbortController(); setLoading(true); setError(""); setEpisodes([]);
    setThrough(season?.through_episode?.toString() || "");
    void (async () => { try {
      const token = await getToken(); if (!token) throw new Error("Please sign in again.");
      const response = await fetch(`${base}/api/library/${title.id}/seasons/${seasonNumber}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
      if (!response.ok) throw new Error(await errorText(response));
      const found: TvEpisode[] = await response.json();
      if (!controller.signal.aborted) setEpisodes(found);
    } catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load episodes"); }
    finally { if (!controller.signal.aborted) setLoading(false); }
    })();
    return () => controller.abort();
  }, [title.id, seasonNumber, getToken]);
  async function update(clear: boolean) {
    if (seasonNumber === null) return;
    setSaving(true); setError("");
    try {
      const token = await getToken(); if (!token) throw new Error("Please sign in again.");
      const response = await fetch(`${base}/api/library/${title.id}/seasons/${seasonNumber}`, {
        method: clear ? "DELETE" : "PUT",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: clear ? undefined : JSON.stringify({ through_episode: through ? Number(through) : null }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      if (clear) setEpisodes((items) => items.map((item) => ({ ...item, watched: false })));
      else setEpisodes(await response.json());
      setSeasons((items) => items.map((item) => item.number === seasonNumber ? {
        ...item, marked_at: clear ? null : new Date().toISOString(), through_episode: clear ? null : through ? Number(through) : null,
      } : item));
      await onUpdated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save season progress"); }
    finally { setSaving(false); }
  }
  const aired = episodes.filter((item) => item.air_date && item.air_date <= new Date().toISOString().slice(0, 10));
  return <section className="tv-progress" aria-label="TV season progress"><div className="tracking-heading"><h3>Episodes</h3>{season?.marked_at && <span>{episodes.filter((item) => item.watched).length} watched</span>}</div>
    <p>Mark a season as watched so far. Episodes released later stay unwatched.</p>
    {seasons.length > 0 && <label>Season<select value={seasonNumber ?? ""} onChange={(event) => setSeasonNumber(Number(event.target.value))}>{seasons.map((item) => <option key={item.number} value={item.number}>{item.name}</option>)}</select></label>}
    {loading ? <p role="status">Loading episodes…</p> : episodes.length > 0 ? <><div className="episode-list">{episodes.map((item) => <div key={item.number} className={item.watched ? "episode watched" : "episode"}><span>{String(item.number).padStart(2, "0")} · {item.name}</span><small>{item.watched ? "Watched" : item.air_date || "Date unknown"}</small></div>)}</div><label>Mark watched<select value={through} onChange={(event) => setThrough(event.target.value)}><option value="">All aired episodes</option>{aired.map((item) => <option key={item.number} value={item.number}>Through episode {item.number}</option>)}</select></label><div className="episode-actions"><button type="button" disabled={saving || !aired.length} onClick={() => void update(false)}>{saving ? "Saving…" : "Save progress"}</button>{season?.marked_at && <button type="button" disabled={saving} onClick={() => void update(true)}>Clear mark</button>}</div></> : !error && <p>No episodes are listed yet.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}

function TrackingDetails({ title, entry, saving, onSave }: { title: Title; entry: Entry; saving: boolean; onSave: (id: string, status: Status, details: EntryDetails) => Promise<void> }) {
  const [rating, setRating] = useState(entry.rating_half_steps?.toString() || "");
  const [review, setReview] = useState(entry.review || "");
  const [favorite, setFavorite] = useState(entry.favorite);
  const [precision, setPrecision] = useState(entry.date_precision);
  const [watchedDate, setWatchedDate] = useState(entry.completed_on || "");
  const [platforms, setPlatforms] = useState(entry.platforms.join(", "));
  const [lists, setLists] = useState(entry.lists.join(", "));
  function names(value: string) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const completedOn = entry.status === "completed" && precision !== "none" && watchedDate
      ? precision === "month" ? `${watchedDate.slice(0, 7)}-01` : watchedDate : null;
    void onSave(title.id, entry.status, {
      completed_on: completedOn,
      date_precision: completedOn ? precision : "none",
      rating_half_steps: rating ? Number(rating) : null,
      review: review.trim() || null,
      favorite,
      platforms: title.media_type === "game" ? names(platforms) : [],
      lists: names(lists),
    });
  }
  return <details className="tracking-details"><summary>More details <span>Rating, date, notes & lists</span></summary>
    <form onSubmit={submit}>
      <label>My rating<select value={rating} onChange={(event) => setRating(event.target.value)}><option value="">No rating</option>{Array.from({ length: 10 }, (_, index) => index + 1).map((step) => <option key={step} value={step}>{(step / 2).toFixed(1)} / 5 stars</option>)}</select></label>
      {entry.status === "completed" && <div className="tracking-date"><label>Completion date<select value={precision} onChange={(event) => { setPrecision(event.target.value); setWatchedDate(""); }}><option value="none">I don’t remember</option><option value="month">Month</option><option value="day">Exact day</option></select></label>{precision !== "none" && <label>{precision === "month" ? "Month" : "Day"}<input type={precision === "month" ? "month" : "date"} value={precision === "month" ? watchedDate.slice(0, 7) : watchedDate} onChange={(event) => setWatchedDate(event.target.value)} required/></label>}</div>}
      <label className="tracking-check"><input type="checkbox" checked={favorite} onChange={(event) => setFavorite(event.target.checked)}/> Add to favorites</label>
      {title.media_type === "game" && <label>Platforms <small>optional, separated by commas</small><input value={platforms} onChange={(event) => setPlatforms(event.target.value)} maxLength={500} placeholder="PC, PlayStation…"/></label>}
      <label>Lists <small>optional, separated by commas</small><input value={lists} onChange={(event) => setLists(event.target.value)} maxLength={500} placeholder="Weekend favorites…"/></label>
      <label>My notes <small>private</small><textarea value={review} onChange={(event) => setReview(event.target.value)} maxLength={10000} rows={3} placeholder="What stayed with you?"/></label>
      <button className="tracking-save" type="submit" disabled={saving}>{saving ? "Saving…" : "Save details"}</button>
    </form>
  </details>;
}

function MissingReportDialog({ draft, onClose, onFound, onReported }: { draft: { name: string; kind: Kind | "" } | null; onClose: () => void; onFound: (title: Title) => void; onReported: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind | "">("");
  const [email, setEmail] = useState("");
  const [choices, setChoices] = useState<Title[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (draft) {
      setName(draft.name); setKind(draft.kind); setEmail(""); setError(""); setSubmitting(false); setChoices([]);
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) dialog.close();
  }, [draft]);
  async function submit(event?: React.FormEvent<HTMLFormElement>, forceReport = false) {
    event?.preventDefault();
    if (!kind || name.trim().length < 2) { setError("Add a title and choose its type."); return; }
    setSubmitting(true); setError("");
    try {
      const response = await fetch(`${base}/api/missing-titles`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), media_type: kind, email: email.trim() || null, force_report: forceReport }) });
      if (!response.ok) throw new Error(await errorText(response));
      const body: MissingReportResult = await response.json();
      if (body.status === "found" && body.title) onFound(body.title);
      else if (body.status === "choices") setChoices(body.choices);
      else onReported();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send your report. Try again.");
    } finally { setSubmitting(false); }
  }
  return <dialog ref={ref} className="report-dialog" onClose={onClose} onClick={(event) => { if (event.target === ref.current) ref.current?.close(); }} aria-label="Report a missing title">
    <button className="dialog-close" onClick={() => ref.current?.close()} aria-label="Close"><Icon name="close" size={21}/></button>
    <form onSubmit={(event) => void submit(event)}>
      <p className="eyebrow">HELP COMPLETE THE CATALOG</p><h2>Missing a title?</h2>
      <p className="report-intro">We’ll check our sources now. If it’s still missing, we’ll queue it for the shared catalog.</p>
      <label>Title name<input autoFocus required minLength={2} maxLength={160} value={name} onChange={(event) => { setName(event.target.value); setChoices([]); }} placeholder="What are you looking for?"/></label>
      <fieldset><legend>Type</legend><div className="report-types">{kinds.map((item) => <label key={item.id}><input type="radio" name="report-kind" value={item.id} checked={kind === item.id} onChange={() => { setKind(item.id); setChoices([]); }} required/><span>{item.label}</span></label>)}</div></fieldset>
      <label>Email <small>optional — only used to tell you when this title is public</small><input type="email" autoComplete="email" maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com"/></label>
      {choices.length > 0 && <div className="report-choices"><h3>Could it be one of these?</h3><p>We found titles with that name. Choose yours, or report a different title.</p><div>{choices.map((title) => <button key={title.id} type="button" onClick={() => onFound(title)}><span>{title.name}<small>{year(title)} · {title.provider.toUpperCase()}</small></span><Icon name="arrow" size={17}/></button>)}</div><button className="report-none" type="button" disabled={submitting} onClick={() => void submit(undefined, true)}>None of these — report it</button></div>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {!choices.length && <button className="report-submit" type="submit" disabled={submitting}>{submitting ? "Checking sources…" : "Check & report title"}<Icon name="arrow" size={18}/></button>}
    </form>
  </dialog>;
}
