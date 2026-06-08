# Varsten marketing site

The public-facing landing page for **varsten.ai**. Standalone Next.js App Router
app, deliberately decoupled from the authenticated dashboard in `../frontend`
(no Auth0, no app shell) so the marketing surface stays lightweight.

It reuses the same hand-rolled CSS custom-property design system (tokens copied
into `app/globals.css`); no Tailwind or UI library.

```bash
npm install
npm run dev     # http://localhost:3000
npm run build
```
