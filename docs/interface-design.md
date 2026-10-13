# Interface direction

Status: implemented as a design iteration on 2026-10-13; open for user review.

The interface treats the catalog as a personal archive rather than a marketing page. Discovery, search, and the private library each have one clear purpose. Posters carry visual interest; descriptions and tracking choices appear in a focused title sheet when someone asks for them.

## Responsive structure

- **Phone and tablet:** compact header, three-item bottom navigation, two-column search results, swipeable release rows with visible arrow controls, and a title sheet anchored to the bottom edge. Fixed navigation respects safe-area insets.
- **Desktop:** persistent left navigation, wider poster grid, compact release rows, and a centered title dialog. The search screen remains one unified search across movies, TV series, and games.
- Browser Back moves between Discover, Search, and My library. The title dialog can be closed with its visible button, Escape, or the backdrop.

## Visual and interaction rules

- System typography, a restrained dark canvas with a warm accent, and a complete light appearance. The user's theme choice is saved locally.
- One hierarchy of surfaces, borders, and muted text in each appearance. Poster images reserve their aspect ratio so results do not jump while loading.
- Navigation and action targets are at least 44 CSS pixels tall. Press, hover, focus, loading, selected, empty, and error states are explicit.
- Motion gives immediate feedback and spatial continuity. Reduced-motion, reduced-transparency, and increased-contrast preferences have CSS alternatives.
- Descriptions and tracking controls stay out of the browsing grid. Saving remains unavailable in preview mode until Clerk is configured.

The design uses the apple-design principles of purpose, agency, direct feedback, and spatial consistency, together with ui-ux-pro-max guidance for responsive navigation, contrast, touch targets, and clear form states. This is an implementation direction, not a claim that the visual preference has been finally approved.
