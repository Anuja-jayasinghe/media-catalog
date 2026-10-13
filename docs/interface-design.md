# Interface direction

Status: revised design iteration on 2026-10-13; open for user review.

The catalog uses a cinematic, content-first interface. Movies, TV series, and games stay in separate sections and dedicated discovery pages. Search keeps one input but presents each media type in its own result group. The private library uses the same grouping.

## Responsive structure

- A transparent top header holds direct links to Home, Movies, TV series, Games, My library, and Search. There is no sidebar or fixed bottom navigation. On narrow screens, the links scroll horizontally without covering the content.
- Home has a featured title and separate movie, series, and game collections. Each category page offers Popular, New releases, and Coming soon, then loads more results as the user scrolls. A visible Load more control remains available.
- Posters are the main browse surface. The poster opens a trailer if one is available; otherwise the visitor goes to IMDb for a movie or TV series with a known IMDb ID, TMDB as a fallback, or IGDB for games. A separate plus control opens tracking without leaving the catalog.
- Browser Back moves between pages. The title dialog can be closed with its visible button, Escape, or the backdrop.

## Visual and interaction rules

- Dark surfaces, large title typography, restrained lime accents, and poster artwork create a cinematic feel without reproducing another service's branding.
- Poster frames reserve their aspect ratio. Images below the viewport load lazily. Loading, empty, error, pressed, focus, and selected states are visible.
- Touch controls use comfortable targets; keyboard focus remains visible. Motion is restrained and reduced-motion and reduced-transparency preferences have CSS alternatives.
- Tracking controls stay in the title dialog. Saving remains unavailable in public preview until Clerk is configured.

This design applies the apple-design principles of direct feedback and spatial consistency and the ui-ux-pro-max guidance for hierarchy, responsive behavior, contrast, and touch targets. It remains a reviewable implementation, not a final visual approval.
