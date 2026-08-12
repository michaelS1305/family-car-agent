# Family Car Agent

A Telegram-based AI assistant for managing a shared family car.

Family Car Agent combines natural-language conversation, shared-car
reservations, automatic CarPlay-based driver tracking, family-scoped
data isolation, and location-aware vehicle release in a single
lightweight service.

> **Status:** Functional MVP. The core flows are deployed and working;
> screenshots and final handover testing are being added.

## Why I Built It

Sharing one car between several family members creates a surprisingly
repetitive coordination problem:

-   Who has the car right now?
-   Is it available tonight?
-   Has someone already reserved it for tomorrow?
-   Who used it recently?
-   Did the last driver remember to say that the car was returned?

Family Car Agent turns those interactions into a conversational
workflow. Family members can talk to a Telegram bot in natural language,
while iPhone CarPlay automations update the current driver
automatically.

## Core Features

### Conversational car assistant

The Telegram bot uses Gemini with tool calling to answer questions and
perform supported actions without inventing database state.

Examples of supported workflows include:

-   Checking whether the car is currently available
-   Asking who currently has the car
-   Viewing recent car usage
-   Creating a reservation using natural language
-   Viewing personal or family reservations
-   Updating an existing reservation
-   Cancelling a reservation

Reservation updates and cancellations require confirmation before the
database is changed.

### Family-scoped access

Users belong to a family, and car state, history, and reservations are
scoped to that family.

A user joining an existing family must provide the matching family
information and family code during onboarding. Reservation modification
and cancellation are additionally restricted to the user who created the
reservation.

### Automated CarPlay driver tracking

During onboarding, iPhone users install two Apple Shortcuts:

-   `Connect to CarPlay`
-   `Disconnect from CarPlay`

The onboarding flow then guides the user through creating the
corresponding iOS CarPlay automations.

When CarPlay connects, the backend records that user as the current
driver. When another family member connects, the system can hand over
the active car session to the new driver.

### Location-aware disconnect

A CarPlay disconnect does not automatically release the vehicle from
anywhere.

The disconnect shortcut sends the device location to the backend. The
car is released only when the current driver is within the configured
home radius. This prevents temporary CarPlay disconnects away from home
from incorrectly marking the shared car as available.

### Reservation conflict protection

Reservations are checked against active reservations belonging to the
same family before being created or updated.

The database layer performs the conflict check and write within the same
pooled database connection/transaction.

### Conversation context

Recent user/assistant messages are stored and supplied to the AI agent
so that short follow-ups such as confirmations, times, or references to
a previous reservation can be understood in context.

## Architecture

``` text
                         ┌─────────────────────┐
                         │   Family Member     │
                         │ Telegram / iPhone   │
                         └──────────┬──────────┘
                                    │
                    ┌───────────────┴────────────────┐
                    │                                │
             Telegram Webhook                 CarPlay Shortcut
                    │                         Connect / Disconnect
                    │                                │
                    └───────────────┬────────────────┘
                                    ▼
                         ┌─────────────────────┐
                         │ FastAPI Application │
                         │      Render         │
                         └──────────┬──────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
     ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
     │ Gemini Agent  │      │ Car Service   │      │  Onboarding   │
     │ + Tool Calls  │      │ + Geofencing  │      │    Flow       │
     └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
             │                      │                      │
             └──────────────────────┼──────────────────────┘
                                    ▼
                         ┌─────────────────────┐
                         │ PostgreSQL          │
                         │ Supabase            │
                         │ Connection Pool     │
                         └─────────────────────┘
```

## Request Flow

### Telegram

1.  Telegram sends an update to `/telegram/webhook`.
2.  The backend identifies the user by Telegram chat ID.
3.  New users or users with an active onboarding session are routed to
    the onboarding state machine.
4.  Registered users are routed to the Gemini agent.
5.  Gemini can call only the backend tools exposed for the current user
    and family.
6.  Tool functions query or modify PostgreSQL.
7.  The final response is sent back through the Telegram Bot API.

### CarPlay

1.  The iPhone CarPlay automation runs an Apple Shortcut.
2.  The shortcut sends the user's private shortcut token to the backend.
3.  `/car/connect` identifies the user and records the active driver.
4.  `/car/disconnect` also receives location coordinates.
5.  The backend verifies that the requester is the current driver and is
    close enough to the family home before releasing the car.

## Tech Stack

  Layer                   Technology
  ----------------------- -----------------------------------------
  Backend API             Python, FastAPI, Uvicorn
  AI                      Google Gemini (`google-genai`)
  Messaging               Telegram Bot API
  Database                PostgreSQL hosted on Supabase
  Database driver         Psycopg 3
  Connection management   `psycopg_pool.ConnectionPool`
  Geocoding               OpenStreetMap Nominatim
  Mobile automation       Apple Shortcuts + CarPlay automations
  Deployment              Render
  Configuration           Environment variables / `python-dotenv`

## Database Model

The application uses the following core tables:

### `families`

Stores the family name, six-digit family code, home address, and home
coordinates.

### `users`

Stores each family member, their Telegram chat ID, private shortcut
token, and `family_id`.

### `car_events`

Stores connect/disconnect events used to determine the current driver
and recent vehicle history.

### `reservations`

Stores reservation owner, start/end time, status, and creation
timestamp.

### `conversation_messages`

Stores recent user/assistant conversation context for the AI agent.

### `onboarding_sessions`

Stores the current onboarding step and temporary onboarding state for
users who have not completed setup.

## Security Design

The project intentionally keeps database access on the server side.

-   Secrets are loaded from environment variables and `.env` is excluded
    from Git.
-   Supabase is used as hosted PostgreSQL through a direct database
    connection.
-   The Supabase Data API is disabled because the application does not
    require browser/client-side database access.
-   Database connections are managed through a bounded connection pool
    rather than one shared global connection.
-   Family-specific queries are scoped using `family_id`.
-   Shortcut tokens identify CarPlay requests without exposing internal
    user IDs.
-   Users cannot modify or cancel another user's reservation.
-   Car disconnects are accepted only from the active driver and only
    near the configured family home.
-   Gemini is not trusted as the source of truth for car state or
    reservations; factual operations are performed through backend tools
    and database queries.

## AI Agent Design

Gemini receives:

-   Current date and time
-   Current user ID and name
-   Current family ID
-   Recent conversation history
-   The current user message

It can call a limited set of Python tools for:

-   Current car status
-   Last driver
-   Recent car events
-   Creating reservations
-   Reading personal reservations
-   Reading family reservations
-   Updating reservations
-   Cancelling reservations

The system instruction explicitly prevents the model from inventing car
state, reservation data, or successful mutations.

## Onboarding Flow

A new Telegram user can either create a family or join an existing one.

### Create a family

The bot collects:

1.  Family name
2.  Home city
3.  Street
4.  House number
5.  Address confirmation
6.  User name

The address is geocoded and stored as the family's home location. A
six-digit family code is generated for inviting other members.

### Join a family

The bot collects:

1.  Family name
2.  Home city
3.  Street
4.  House number
5.  Family code
6.  User name

The family code is limited to three attempts. Incorrect input of any
format counts as an attempt.

After registration, the bot provides the user's shortcut token and
guides the user through installing and configuring the two CarPlay
shortcuts.

## Project Structure

``` text
family-bot-agent/
├── main.py                 # FastAPI routes and Telegram webhook
├── ai_service.py           # Gemini agent, prompt and tool definitions
├── onboarding_service.py   # Stateful family/user onboarding
├── car_service.py          # Connect, disconnect, handover and geofence logic
├── database.py             # PostgreSQL schema, queries and connection pool
├── telegram_service.py     # Telegram API messaging
├── geocoding_service.py    # Address geocoding
├── models.py               # FastAPI/Pydantic request models
├── requirements.txt
└── .gitignore
```

## Local Setup

### 1. Clone the repository

``` bash
git clone <YOUR_REPOSITORY_URL>
cd family-bot-agent
```

### 2. Create a virtual environment

``` bash
python -m venv .venv
```

Activate it using the command appropriate for your operating system.

### 3. Install dependencies

``` bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a local `.env` file:

``` env
DATABASE_URL=your_postgresql_connection_string
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
```

Do not commit this file.

### 5. Run the API

``` bash
uvicorn main:app --reload
```

The root health endpoint is available at:

``` text
GET /
```

## Deployment

The application is designed to run as a web service.

The deployed service needs the same environment variables used locally.
Telegram should be configured to send webhook updates to:

``` text
https://<your-domain>/telegram/webhook
```

The CarPlay shortcuts call:

``` text
POST /car/connect
POST /car/disconnect
```

The application initializes the required PostgreSQL tables on startup.

## Screenshots

Screenshots will be added here after the final UI/documentation pass.

Suggested examples:

-   Telegram onboarding
-   Natural-language reservation conversation
-   Current car status
-   iPhone CarPlay automation setup

## Current Limitations

-   The CarPlay automation flow is designed for iPhone.
-   Home detection uses a configured geographic radius rather than
    vehicle telemetry.
-   The project currently manages one shared car per family.
-   The service is an MVP and does not yet include a separate web
    dashboard.

## Future Improvements

Potential next steps include:

-   Multiple cars per family
-   Admin controls for family management
-   Reservation reminders and notifications
-   A small web dashboard
-   Improved audit/event views
-   Additional automated tests
-   More granular operational monitoring

## Author

**Michael Sandrovich**

Built as a practical end-to-end project combining backend development,
PostgreSQL, AI tool calling, API integrations, deployment, and mobile
automation.
