# Statathon Dashboard

Next.js frontend for the Statathon statistical analysis platform.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Copy environment variables:
```bash
cp .env.local.example .env.local
```

3. Update `.env.local` with your API URL (default: `http://localhost:8000`)

4. Run development server:
```bash
npm run dev
```

The app will be available at `http://localhost:3000`

## Features

- **Upload Page** (`/upload`): Drag-and-drop CSV/Excel file upload
- **Dataset View** (`/datasets/[id]`): Dataset overview and analysis trigger
- **Analysis Results** (`/analysis/[id]`): Outlier detection, semantic mapping, and decision interface
- **Report Viewer** (`/reports/[id]`): PDF report preview and download

## Components

- `DataTable`: Paginated data grid with column insights
- `OutlierCard`: Outlier visualization with decision buttons (keep/delete/normalize)
- `ConfidenceScore`: Visual confidence indicators
- `ReportPreview`: Embedded PDF viewer with react-pdf
