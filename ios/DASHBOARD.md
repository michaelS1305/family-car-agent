# Native Dashboard (Dev)

DashboardScreen uses the authenticated name supplied by EntryModel. Greeting takes
the first whitespace-separated word, falling back to “היי”. It does not fetch or
persist account data. Logout calls the existing EntryModel.logout action unchanged.

The Canvas follows Android DashboardScreen.kt's draw order: radial depth, diagonal
body gradient, alternating sector tint, five white dividers, outer rings, hub shadow,
hub gradient and hub border. Radius = 0.46 × diameter; hub = 0.23 × radius;
sector start = −126°, sweep = 72°. No new animation or Glass is applied to the wheel.

Five complete archive PNGs, including lettering, render at 0.5 × diameter and a
vertical offset of −0.07 × image size. Each sits over a separate 0.25D × 0.28D button,
minimum 44 points, with physical (non-mirrored) Android anchors. The originals are
not cropped or edited. Alpha bounds in their 512×512 canvases are:

| Asset | Bounds (left, top, right, bottom; exclusive) |
|---|---|
| family_icon | 131, 154, 343, 399 |
| vehicles_icon | 181, 186, 333, 379 |
| settings_icon | 86, 161, 351, 425 |
| history_icon | 101, 178, 362, 379 |
| booking_center_icon | 167, 155, 345, 476 |

Layout uses the shell's available safe-area size, after the floating mode bar's
reserved space. Compact mode below 540 points uses a 64-point wordmark/24-point
greeting, otherwise 85/28. Diameter is the smaller of available width minus 16 and
remaining height after header, greeting, 6-point gap, 8-point outer padding and
70-point logout reserve. Exceptionally short screens scroll at a 176-point minimum
diameter rather than overlap controls. Long names scale within one greeting line;
Android permits two lines. Native NavigationStack supplies destination back navigation.

The shell retains Chat and its model while switching modes. DashboardNavigation
holds value-based destinations, ignores duplicate opens and clears its path when
authenticated owner, user, family or session generation changes. The five destinations
are explicitly temporary placeholders. The shared mode bar is hidden within them.

Checks: `Checks/run-dashboard-checks.sh`, `Checks/check-dashboard-resources.py`,
and the existing `Checks/run-ci-checks.sh`. Pass an unsigned .app directory to the
resource checker to verify packaged PNG hashes. Geometry checks do not prove visual
equivalence or native navigation/VoiceOver behavior. Validate iPhone 13 screenshot
alignment, all five taps/back paths, compact layout, logout and retained Chat state
on device before claiming end-to-end completion. No live API request is needed to
render the Dashboard beyond the existing authenticated account bootstrap.
