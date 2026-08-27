# NewsAgent Deployment Guide

## Backend Deployment (Railway/Render)

### Option A: Railway
1. Connect GitHub repo
2. Set root directory to `/`
3. Set build command: `pip install -r backend/requirements.txt`
4. Set start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables:
   - `DATABASE_URL` (Railway provides PostgreSQL URL)
   - `JWT_SECRET` (generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"`)
   - `CORS_ORIGINS` (your app's domain or `*` for development)
   - `FIREBASE_CREDENTIALS_PATH` (optional, for push notifications)
   - `TRADINGVIEW_WEBHOOK_TOKEN` (optional, for TradingView live alerts — see below)

### Option B: Render
1. Create new Web Service from GitHub repo
2. Runtime: Python 3
3. Build command: `pip install -r backend/requirements.txt`
4. Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Add same environment variables as above
6. Add PostgreSQL database (Render provides managed PostgreSQL)

### Database Setup
- Backend auto-creates SQLite tables on startup
- For production: set DATABASE_URL to PostgreSQL connection string
- Run migrations: `alembic upgrade head` (after Phase 1C migration)

## TradingView Live Alerts

To enable the inbound TradingView webhook and live dashboard:

1. Set the webhook secret on the backend:
   - `TRADINGVIEW_WEBHOOK_TOKEN` (generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`)
   - If unset, the webhook endpoint returns `503`.
2. The webhook URL must be **HTTPS-reachable from TradingView's servers** (no localhost). On Railway/Render the service is already served over HTTPS — point TradingView at:
   - `https://<your-backend-host>/api/v1/webhook/tradingview?token=<secret>`
3. The live dashboard is served at `https://<your-backend-host>/dashboard` (a single static file at `backend/static/dashboard.html`). It's exposed by the same FastAPI service, so no extra routing is needed — just confirm the host serves it.
4. Optional tuning env vars (defaults shown):
   - `COALESCE_WINDOW_SECONDS=60` — burst window for collapsing alerts into one card
   - `COALESCE_GROUP_KEY=category,ticker` — fields defining the coalescing group
   - `ALERT_HISTORY_LIMIT=20` — alerts retained per group
   - `ALERT_PRUNE_AFTER_DAYS=3` — prune coalesced groups older than this
   - `TRADINGVIEW_FORWARD_DISCORD=false` — also forward alerts to Discord routes

> If your platform terminates WebSockets, ensure `/api/v1/ws/live` is allowed — the dashboard relies on it for the live stream.

## Mobile App Build & Submit

### Prerequisites
- Apple Developer Program ($99/year): https://developer.apple.com/programs/
- Google Play Developer ($25 one-time): https://play.google.com/console/
- Install EAS CLI: `npm install -g eas-cli`
- Login: `eas login`

### Configure
1. Update `mobile/app.json`:
   - Set `expo.extra.eas.projectId` (from `eas init`)
   - Set `expo.ios.bundleIdentifier`
   - Set `expo.android.package`

2. Update `mobile/eas.json`:
   - Set Apple credentials in `submit.production.ios`
   - Set Android service account in `submit.production.android`

3. Update API URL in mobile app:
   - Edit `mobile/src/api/client.ts` BASE_URL to production backend URL
   - Or configure via Settings screen in the app

### Build
```bash
cd mobile

# Build for both platforms
eas build --platform ios --profile production
eas build --platform android --profile production

# Or build for testing first
eas build --platform ios --profile preview
```

### Submit
```bash
# Submit to App Store
eas submit --platform ios --profile production

# Submit to Google Play (internal testing track)
eas submit --platform android --profile production
```

### TestFlight / Internal Testing
- iOS: Build appears in TestFlight after processing (~10-30 min)
- Android: Build appears in Internal Testing track immediately

### Production Release
- iOS: Submit for App Review from App Store Connect
- Android: Promote from Internal Testing to Production in Play Console

## Firebase Setup (Push Notifications)

1. Create project at https://console.firebase.google.com
2. Add iOS app (bundle ID: com.newsagent.app)
3. Add Android app (package: com.newsagent.app)
4. Download service account key JSON
5. Set `FIREBASE_CREDENTIALS_PATH` env var on backend server
6. The mobile app uses Expo Push Tokens which route through Expo → FCM → APNs

## Cost Summary
| Item | Cost |
|---|---|
| Backend hosting (Railway/Render) | $5-20/month |
| PostgreSQL (managed) | $0-7/month |
| Apple Developer Program | $99/year |
| Google Play Developer | $25 one-time |
| Firebase (FCM) | Free |
| Domain (optional) | ~$12/year |
