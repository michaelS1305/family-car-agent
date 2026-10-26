# FCA iOS — Asset System

## Status
- 40 PNG assets prepared and validated in the isolated Probe app on a real iPhone.
- Source assets: Windows repository `assets/`.
- iOS resource directory: `Sources/FamilyCarAgent/Resources/AppAssets/`.
- SwiftPM integration: `.copy("Resources/AppAssets")`.
- Asset loader: `Sources/FamilyCarAgent/AppAsset.swift`.
- Current EntryAssets are preserved unchanged.
- Dark Mode-specific variants are future work.

## Image preparation
- Original PNG files are the source of truth.
- Most icons and vehicle illustrations are exported at 512px.
- Rectangular assets preserve their aspect ratio.
- Login buttons and the app icon retain their original source files.
- Do not vectorize the original PNGs into SVG for this pipeline.
- Preserve transparency and transparent margins.

## Export workflow
Reusable Windows PowerShell script:
`%TEMP%\fca-ios-export-pipeline\Export-FCAAssets.ps1`

The script reads source PNGs and generates a new output directory
with `assets-report.csv`. It does not overwrite existing outputs.

The script and original inputs must be retained when moving this
workflow to a permanent development environment. Windows Temp is
not permanent storage.

## Adding an asset
1. Add its original PNG to the appropriate category under `assets/`.
2. Run the PowerShell export script to a NEW output directory.
3. Review the new asset's dimensions, transparency and appearance.
4. Copy the updated package into iOS Dev's AppAssets after review.
5. Confirm the SwiftPM resource declaration and loader path.
6. Run entry-resource checks, build and test on an iPhone.

## Loading an image
Example:

`AppAssetImage(path: "icons/archive/dashboard_icon.png")`

Paths are relative to AppAssets, with the filename extension.
The central loader has been added to iOS Dev, but its direct runtime
behavior still requires validation when a screen begins using it.

## Current entry screens
`Resources/EntryAssets` remains independent and unchanged.
Its images will be migrated only when explicitly approved.
Do not modify Apple/Google authentication while doing asset work.

## Verification
- 40/40 PNG files passed structural validation.
- All 40 exported files reproduced byte-for-byte in the export test.
- The Probe app displayed the assets on an iPhone successfully.
- iOS Dev previously built, signed and ran successfully with AppAssets.
- A final build after adding AppAsset.swift is still required.

## Deferred
- Additional assets.
- Dark Mode variants where needed.
- EntryAssets migration.
- Production integration and Git changes.
