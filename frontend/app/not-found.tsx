import Link from "next/link";

export default function NotFound() {
  return (
    <main className="not-found-page" aria-labelledby="not-found-title">
      <div className="not-found-card">
        <Link className="not-found-brand" href="/" aria-label="MTGL home">
          <span>M<span className="not-found-dot">.</span></span> MTGL
        </Link>
        <p className="not-found-code">404 · PAGE NOT FOUND</p>
        <h1 id="not-found-title">We can’t find that page.</h1>
        <p className="not-found-copy">That address doesn’t lead to a page here. Head back to the catalog and find something worth remembering.</p>
        <div className="not-found-actions">
          <Link className="not-found-primary" href="/">Back to home</Link>
          <Link className="not-found-secondary" href="/?view=movie">Browse movies</Link>
        </div>
      </div>
    </main>
  );
}
