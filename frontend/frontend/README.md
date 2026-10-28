# ClipCut AI frontend

The React/Vite client for ClipCut AI. See the [project setup guide](../../README.md)
for local installation, running the backend and frontend, video-processing
requirements, API routes, and troubleshooting.

## Frontend commands

```powershell
npm ci
npm run dev
npm run lint
npm run build
```

The development server runs on port 5173 and proxies `/api` and `/media` to
the Django backend on port 8000.
