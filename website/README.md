# FCA public website — visual Phase 1

Independent React/TypeScript/Vite site. No changes or dependency on the existing web/PWA, authentication or Backend.

## Local review

```powershell
cd C:\Projects\family-bot-agent\website
pnpm install --frozen-lockfile
pnpm dev
```

Open the localhost address printed by Vite. Validation: `pnpm test`, `pnpm typecheck`, `pnpm build`. Production preview: `pnpm preview` (local only).

## Assets and fidelity

- `fca-road-logo.png`: unchanged supplied road wordmark.
- `fca-app-icon.png`: unchanged supplied app icon, also used inside the phone illustration.
- `family-road.png`: unchanged supplied `משפחה בנסיעה על כביש מתפתל.png` (1672×941); not the companion illustration.
- `fca-road-logo-white.svg`: existing approved repository dark/white wordmark, unchanged.
- Waves, phone/leaves, decorative marks and small line icons are SVG/CSS reconstructions, not screenshot crops. Store badges are visual reconstructions, not downloaded official badge files.
- No exact Hebrew font was supplied. System font rendering varies by device; this is not a claim of pixel-perfect typography.

## Phase 1 interactions

Four header anchors, mobile menu (including Escape), hero section links and native keyboard-accessible FAQ disclosures work locally. Store, support and legal actions are disabled and explicitly marked as unavailable. FAQ answers are placeholders, not invented product guidance. No external destinations, network API calls, analytics, service workers or authentication are implemented.

The hero illustration intentionally differs from the mockup as requested. Responsive layouts use four/two feature columns and a mobile navigation menu. Real store URLs, support/contact destinations, legal documents and FAQ copy remain required before publication.

## Application capabilities

`/features` renders the capabilities page using the same Header/Footer and ordinary browser links (no routing dependency). Vite supports direct access and refresh locally. Any future static hosting must serve index.html for /features; no hosting configuration is changed here.

Phone/checklist, cars, leaves, road, section icons and illustrations are SVG reconstructions from the approved capabilities mockup. Existing branding and the original family-road image are reused unchanged. These reconstructions and system typography are not pixel-identical to the supplied raster mockup. The homepage stylesheet is unchanged by this page; all new styles are page-scoped.

## Support Center and shared FAQ

`/support` reuses the Header/Footer. All fourteen approved FAQ entries live in `src/faqData.ts`; both homepage and Support use `SharedFAQ`. Four questions appear initially, with keyboard-accessible Show More/Less and native disclosure controls. Categories intentionally have no links or click affordances. Contact remains unavailable. The hero uses the original family-road asset; the envelope and small decorative icons are SVG reconstructions, not exact raster matches. No new dependencies or backend integration.

## Contact prototype

`/contact` provides local-only validation for name, email, three approved subjects, a 1,000-character description and up to five image/PDF files (10 MiB each). Selection checks extension plus MIME when supplied; this is not content/security validation. A future Backend must independently inspect uploads. Files remain in browser memory only; reload/navigation clears the form. Pressing Submit never sends data, clears attachments or claims delivery. The official mailto link opens the user's mail client without automatically sending a message. No support hours are asserted.

Contact visuals reuse the original road artwork and the existing SVG envelope; added name/email fields and prototype disclosure intentionally increase the form height relative to the mockup.

## Family guides

- `/support/family`: implemented family guides only.
- `/support/family/create`: six-step Create Family guide, shared layout and separate content.
- Screenshots: `public/assets/guides/create-family/step-1.jpg` through `step-5.jpg` are unchanged copies of the five supplied Photo JPEGs, corresponding in order to the brief's IMG_3047–IMG_3051 labels. Original dimensions: 591 × 1280. Total: 296,218 bytes. No PNG conversion or UI alteration. Images load lazily and open at original size in a new tab.
- Guide navigation uses the site's existing ordinary links. Vite supports local direct routes and refresh; eventual hosting must retain SPA fallback for these routes, as for `/features` and `/contact`.
- Validation: `pnpm --dir website test`, `pnpm --dir website typecheck`, `pnpm --dir website build`. Local preview: `pnpm --dir website dev`.
- Browser review covered Support → Family → Create, Back/Forward, direct navigation and refresh, desktop and 390px mobile viewport. No horizontal overflow observed. Physical mobile Safari/VoiceOver remains a separate manual check.

## Management guide — publication hold

`/support/family/manage` uses the supplied original Photo 1 JPEG (brief label IMG_3052.png), unchanged. Its visible family code and family information have NOT been verified as demonstration data. Owner confirmation is required before publishing this image or deploying a build containing it. Local integration/build only; no live publication authorized.

## Phase 5B update

The owner has explicitly approved the existing guide screenshots and video for
public use. Earlier publication holds in this document are superseded. See
PHASE5B.md for current routing, SEO, media optimization and validation results.
