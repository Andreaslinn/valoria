# Valoria Frontend

Next.js scaffold for the future Valoria user-facing app.

## Setup

```powershell
cd frontend
npm.cmd install
copy .env.example .env.local
npm.cmd run dev
```

Open `http://localhost:3000`.

## API URL

The frontend reads:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

For the future tunnel/domain:

```env
NEXT_PUBLIC_API_BASE_URL=https://api.valoria.cl
```

The backend must allow the frontend origin through `BACKEND_CORS_ORIGINS`.
