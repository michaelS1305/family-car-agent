# Legacy frontend retired (Phase 5C)

The legacy application source, UI tests, package/build configuration and public
assets have been removed. Do not build or deploy this directory.

Retained: src/legal/legalDocuments.ts is the original legal-copy reference named
by Android's LegalCopy.kt. It is not an executable frontend entry point.
Local ignored node_modules and .env.local were preserved, without reading secrets.

The public website lives in ../website. Web CI still targets this retired directory;
its migration is reserved for Phase 5D. Do not push this intermediate state as a
release. Backend/native APIs and installed native integrations remain unchanged.
