# Phase 5B — local implementation

## Routing and SEO

`src/pageMetadata.ts` is the public route metadata registry. App retains ordinary
browser links and listens for popstate; metadata also refreshes when its pathname
prop changes. Unknown paths render NotFoundPage, with no selected header item,
no canonical/og:url and noindex,follow.

The Vite build generates route-specific HTML heads for all 21 known paths,
404.html, sitemap.xml and robots.txt in dist. Body content is still client-rendered;
this is not full SSR. The sitemap includes 19 indexable routes. The two coming-soon
iPhone guides remain accessible but use noindex,follow and are excluded until
published. Canonicals and sitemap use https://familycaragent.com; no lastmod dates
are invented. Open Graph uses the retained original PNG logo for compatibility.

A React 404 is not an HTTP status. A host rewriting every URL to index.html may
return 200 even while React renders this page. Generated 404.html does not configure
the host by itself. Hosting must separately serve route HTML and a true 404 fallback.
No Render configuration was changed. Development indexing restrictions must also
be configured separately before deployment; these are production build directives.

## Artwork and optimization

The supplied 1536x1024 mockup was cropped at (0,490)-(1536,775) for the illustration,
and (296,220)-(439,289) for a decorative cloud. No text/buttons are baked into the
artwork. It retains the original background, not a transparent isolated drawing.
Typography uses the existing site fonts and is not pixel-identical to the mockup.
Header/Footer remain the existing components, rather than copying mockup navigation.

Pillow from the existing Python 3.12 installation produced lossless WebP with
exact=True. RGBA pixel equality, transparency and dimensions were verified:

| Asset | Original bytes | WebP bytes |
| --- | ---: | ---: |
| fca-road-logo | 1,400,688 | 514,484 |
| fca-app-icon | 785,759 | 486,890 |
| family-road | 604,424 | 357,928 |

Original files remain. Existing white SVG remains unchanged. A separate 48x48 PNG
favicon is derived from the original app icon. Keeping originals means deployment
storage is not reduced, but page image transfer is reduced.

No ffmpeg/ffprobe executable or imageio_ffmpeg was available in the checked local
tool locations. The 12,693,344-byte MOV remains unchanged, with controls,
preload=none and no autoplay. No unvalidated conversion was substituted.

The owner explicitly approved existing guide screenshots/video for public use in
Phase 5B. Earlier pending-publication notes are superseded by that approval; no
media contents were anonymized or altered.

## Validation

pnpm test: 49 passing (includes production build and focused SEO/404/media tests).
pnpm typecheck and pnpm build pass. No lint script is configured.
Browser: local preview, desktop and 390px mobile visual checks; 768px viewport
DOM overflow check; 404 recovery links, Back/Forward, refresh and changing
canonical/title/robots verified. No real contact submission or external service
configuration was used. Physical Safari/VoiceOver and cross-browser video playback
remain unverified.

Commands from website/: pnpm test; pnpm typecheck; pnpm build; pnpm preview.
