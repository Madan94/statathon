# BharatStat Dashboard

Next.js frontend for **BharatStat** — audit-ready survey data intelligence (MoSPI-inspired institutional UI).

## Setup

1. Install dependencies:

```bash
npm install
```

2. Copy environment variables:

```bash
cp .env.local.example .env.local
```

3. Set `NEXT_PUBLIC_API_URL` in `.env.local` (default: `http://localhost:8000`)

4. Run the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Workflow

1. **Home** (`/`) — product overview and trust features
2. **Upload** (`/upload`) — drag-and-drop CSV/Excel (optional R2 presigned upload)
3. **Dataset** (`/datasets/[id]`) — profile KPIs and async analysis
4. **Analysis** (`/analysis/[id]`) — tabbed workspace (overview, semantic, validation, outliers, imputation, report)
5. **Report** (`/reports/[id]`) — PDF preview, metadata sidebar, download

## UI stack

- Tailwind CSS v4 design tokens (navy + saffron accent)
- `lucide-react` icons
- `sonner` toasts (no browser `alert()`)
- App shell with sidebar (desktop) and mobile drawer

## Components

| Area | Components |
|------|------------|
| Layout | `AppShell`, `Sidebar`, `TopBar`, `WorkflowStepper`, `PageHeader` |
| UI | `Button`, `Card`, `Badge`, `Tabs`, `StatCard`, `Alert`, `EmptyState`, `Skeleton` |
| Analysis | `HealthSummary`, `SemanticTable`, `ValidationTable`, `ImputationList`, `OutlierGrid` |
| Upload | `FileDropzone` |

## Screenshots checklist (for demos)

- [ ] Landing hero with BharatStat wordmark
- [ ] Upload with workflow stepper
- [ ] Dataset KPI row + analysis progress
- [ ] Analysis tabs (semantic + outliers)
- [ ] Report split layout with hash sidebar

## Accessibility

- Focus rings on interactive controls
- `aria` labels on tabs, dropzone, and toolbar
- `prefers-reduced-motion` respected in global CSS
