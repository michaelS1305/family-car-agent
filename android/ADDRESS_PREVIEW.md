# Dev address proposals and Lite Mode preview

All three Android confirmation screens display only coordinates returned by the corresponding authenticated address resolution. CREATE and EDIT continue submitting the opaque resolution token; coordinates are never sent back to authorize saving. JOIN still uses its existing server-owned session, family name, 50-meter match and joining-code verification. JOIN resume responses have no candidate coordinates; a resumed confirmation safely displays text without a map until the address is resolved again.

## Local Maps key

Set `FCA_ANDROID_DEV_MAPS_API_KEY` in the local build process, or add `MAPS_API_KEY` to the existing ignored `android/fca.dev.properties`. Never commit the value. The environment variable takes precedence. Use the dedicated Maps SDK for Android key restricted to `il.fca.companion.dev` and the actual Dev signing certificate SHA-1. Do not use the backend Geocoding credential. No Production key or Firebase changes are required or supplied here.

A missing key disables the preview only. An invalid/restricted key or unavailable network can show a fallback after 15 seconds; there is no saving delay and no location permission. The Maps SDK may retrieve map imagery; no client geocoding is performed.

## Proposal semantics and limits

The backend sends the complete input to Google, without guessing multiword city/street boundaries. One unambiguous house-number token is required. Explicit legacy city/street/house fields also support numeric street names. Multiple numbers in free text require clarification. Results need Israel, exact house number, ROOFTOP, no partial match, finite/in-range coordinates and complete street/city components. Existing distant-result ambiguity rejection remains. Displayed proposal must be explicitly confirmed: city/street spelling equality is no longer required for these proposal endpoints. Legacy component callers remain strict.

## Manual Dev verification still required

Configure the key locally, rebuild Dev, and check CREATE/JOIN/EDIT on a device: Hebrew variants, multiword names, proposal correction, small screens, attribution, disabled gestures/external opening, background/foreground, cancellation/account switch, missing key/offline and token expiry. A map loading successfully is not permission to save. Confirm the actual saved home/geofence changes only after final token-based save. Do not perform live destructive tests. Deploy backend additive coordinate fields before expecting maps; older responses remain supported without a preview.
