# Family Car Agent

Family Car Agent is a standalone PWA for coordinating one shared family car.
It combines Google authentication, family onboarding, reservations, CarPlay
driver tracking, location-aware vehicle release, and a family-scoped Gemini
assistant.

## Current capabilities

- Google sign-in through Supabase Auth
- Create or join a family through the PWA onboarding flow
- Family-scoped car status, event history, and reservations
- Guided iPhone CarPlay and Apple Shortcuts setup
- Automatic connect/disconnect events using a private connection code
- Google Maps address resolution and home-location validation
- App-native Gemini tools with user-specific conversation history

The Main App currently provides the chat-first interface shell. The authenticated
PWA chat API is the next integration step.

## Architecture

```text
React/Vite PWA
      |
      | Supabase access token
      v
FastAPI API on Render
      |
      +-- Supabase JWT verification (ES256/JWKS)
      +-- PostgreSQL connection pool
      +-- Google Maps Geocoding
      +-- Gemini tools
      +-- CarPlay shortcut endpoints
      |
      v
PostgreSQL on Supabase
```

The browser never supplies trusted `user_id` or `family_id` values. Protected
routes derive the authenticated identity from the Supabase JWT and load the
internal user and family mapping on the server.

CarPlay shortcuts authenticate using a separate high-entropy connection code.
The backend derives the user and family from that code before reading or writing
car state.

## Backend modules

- `main.py` — FastAPI routes and configuration
- `auth_service.py` — Supabase JWT verification and `CurrentUser`
- `database.py` — PostgreSQL schema bootstrap and scoped queries
- `family_creation_service.py` — PWA Create Family flow
- `join_family_service.py` — PWA Join Family flow
- `onboarding_rules.py` — shared validation and normalization rules
- `car_service.py` — connect, disconnect, handover, and geofence logic
- `carplay_setup_service.py` — personal connection-code setup
- `ai_service.py` — app-native Gemini prompt and scoped tools
- `geocoding_service.py` — Google Maps address resolution

## Data isolation

- PWA identity is derived from JWT -> `auth_user_id` -> internal user.
- Family-scoped actions fail closed when the internal user has no family.
- Reservation reads and conflicts are filtered by family.
- Reservation changes are authorized atomically by reservation, user, and
  family in SQL.
- Car events are scoped to the family derived from the connection code.
- Conversation history is user-specific.
- Gemini never chooses `user_id`, `family_id`, or `auth_user_id`; its tools close
  over the validated `CurrentUser`.

## Local setup

Create and activate a virtual environment, then install the backend:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

Create a local `.env` file based on `.env.example`:

```env
DATABASE_URL=your_postgresql_connection_string
SUPABASE_URL=https://your-project-ref.supabase.co
GOOGLE_MAPS_API_KEY=your_server_side_google_maps_api_key
GEMINI_API_KEY=your_gemini_api_key
RUN_DB_INIT=true
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Do not commit `.env` files. Keep `GOOGLE_MAPS_API_KEY` and `GEMINI_API_KEY`
backend-only.

Run the API:

```bash
uvicorn main:app --reload
```

Install and run the frontend:

```bash
cd frontend
npm install
npm run dev
```

The frontend environment is documented in `frontend/.env.example`.

## Production configuration

Backend environment variables:

- `DATABASE_URL`
- `SUPABASE_URL`
- `GOOGLE_MAPS_API_KEY`
- `GEMINI_API_KEY`
- `RUN_DB_INIT=false`
- `CORS_ALLOWED_ORIGINS=https://your-frontend-domain`

Frontend environment variables:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`
- `VITE_API_BASE_URL`

`RUN_DB_INIT` is disabled unless its value is exactly `true`, case-insensitive.
Production schema changes should be explicit migrations rather than startup DDL.
Wildcard CORS origins are rejected.

## Verification

Backend tests:

```bash
python -m unittest discover -s tests -v
```

Frontend verification:

```bash
cd frontend
npm run test:frontend
npm run lint
npm run build
```

## Current limitations

- The PWA chat interface is not connected to the Gemini backend yet.
- No push notification system is implemented.
- The application currently manages one shared car per family.
- CarPlay setup and automations require an iPhone.

## Author

**Michael Sandrovich**
