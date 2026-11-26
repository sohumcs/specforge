# SPECForge frontend

React 19 + TypeScript (Vite), Tailwind 4, TanStack Query, React Flow v13, dnd-kit.

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api to http://localhost:8000)
npm test           # Vitest + Testing Library
npm run lint       # ESLint (typescript-eslint, react-hooks, jsx-a11y)
npm run typecheck  # tsc
npm run build      # production bundle in dist/
```

Set `VITE_API_PROXY` to point the dev proxy at another API. Architecture and design decisions:
`../docs/ARCHITECTURE.md` §7 and `../docs/DECISIONS.md` (ADR-028 to ADR-031).
