# Valoria V2

Next.js15 App Router frontend for the existing Valoria Oracle API. Run `npm ci` and `npm run dev`; build with `npm run build`. Dependency versions are locked in package-lock.json.

Browser API requests use `/backend` on the same origin. next.config.ts forwards only that fixed path to NEXT_PUBLIC_API_BASE_URL; set it to the validated HTTPS Oracle origin in Netlify. Authentication uses the existing bearer token and backend authorization, with no backend secret in public environment variables. Development-only fixtures are disabled in production.

Netlify builds frontend-v2 using the root netlify.toml and its modern automatic OpenNext adapter. Use the release branch and deploy-preview acceptance before production publication. Keep the legacy site and Oracle services unchanged. Exact backend image, release source hashes, deployment IDs and rollback state are recorded in deployment acceptance artifacts.
