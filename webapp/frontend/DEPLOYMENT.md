# Dark STS Detector Frontend Setup & Deployment Guide

## Quick Start

### Prerequisites
- Node.js 18+ and npm 9+
- Backend API running on http://localhost:8000 (development)

### Local Development

```bash
# Navigate to frontend directory
cd webapp/frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Open http://localhost:3000 in your browser. The dev server proxies API calls to http://localhost:8000.

## Project Structure

```
src/
├── components/
│   ├── Dashboard.tsx         # Main dashboard layout
│   ├── Header.tsx            # Navigation header
│   ├── Map.tsx               # Leaflet map component
│   ├── Charts.tsx            # Recharts visualizations
│   ├── EventTable.tsx        # Events table with sorting
│   ├── EventDetail.tsx       # Event detail modal
│   ├── Filters.tsx           # Filter panel
│   ├── StatsCard.tsx         # Stats card component
│   ├── HealthCheck.tsx       # System health indicator
│   ├── DetectionUpload.tsx   # Live detection upload
│   ├── Footer.tsx            # Footer with exports
│   └── Loading.tsx           # Loading states
├── services/
│   └── api.ts               # API client
├── store/
│   └── dashboardStore.ts    # Zustand store
├── App.tsx                  # Root component
├── main.tsx                 # Entry point
└── index.css               # Global styles
```

## Configuration

### Environment Variables

Create `.env.local` if needed:
```bash
VITE_API_URL=http://localhost:8000
```

### Backend Proxy

The Vite dev server proxies `/api` requests to the backend. Configure in `vite.config.ts`:

```typescript
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true
    }
  }
}
```

## Building for Production

```bash
# Build optimized bundle
npm run build

# Preview production build locally
npm run preview
```

Output goes to `dist/` directory (~250KB gzipped).

## Deployment Options

### Docker

```dockerfile
# Build stage
FROM node:18-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

Create `nginx.conf`:
```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;
  
  location / {
    try_files $uri /index.html;
  }
  
  location /api {
    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
}
```

### Vercel

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel
```

Configure `vercel.json`:
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "env": {
    "VITE_API_URL": "@api_url"
  }
}
```

### Hugging Face Spaces

1. Create a new Space with Docker runtime
2. Push code to the Space's Git repository
3. Configure environment in Space settings
4. Space automatically builds and deploys

### Traditional Server (Ubuntu/Debian)

```bash
# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Clone repo and build
git clone <repo>
cd webapp/frontend
npm install
npm run build

# Serve with PM2
npm i -g pm2
pm2 serve dist/ 3000 --name "dark-sts"
pm2 startup
pm2 save
```

## Features

### Dashboard
- Real-time event monitoring
- Interactive Leaflet map with clustered markers
- Event filtering and sorting
- Detailed event inspection modal
- Export to JSON/CSV

### Analytics
- Status distribution (pie chart)
- Confidence distribution (bar chart)
- 7-day trend analysis (line chart)
- Key metrics: total events, dark candidates, confidence, GFW matches

### Maps
- Interactive Leaflet map from Carto (dark tiles)
- Real-time event markers color-coded by status
- Popup with event details on click
- Responsive to screen size

### Filtering
- Filter by status (AIS Visible, Partial, Dark)
- Filter by region
- Confidence threshold slider
- Reset filters button

### Export
- JSON export with full event data
- CSV export for spreadsheet analysis
- Timestamped filenames

## Performance Optimization

- Code splitting via Vite
- Tree-shaking removes unused code
- CSS minification via Tailwind
- Lazy loading heavy components
- Efficient re-renders with Zustand
- Image optimization (defer non-critical)

## Browser Support

| Browser | Min Version |
|---------|-------------|
| Chrome | 90+ |
| Firefox | 88+ |
| Safari | 14+ |
| Edge | 90+ |

## Troubleshooting

### API Connection Failed
- Check backend is running on http://localhost:8000
- Verify proxy configuration in vite.config.ts
- Check CORS headers in backend

### Map Not Loading
- Verify Leaflet CSS is loaded
- Check tile server (Carto) is reachable
- Browser console for specific errors

### Slow Performance
- Check Network tab for large assets
- Use React DevTools Profiler
- Verify backend response times
- Check for excessive re-renders in Zustand

### Build Issues
- Clear node_modules: `rm -rf node_modules && npm install`
- Clear Vite cache: `rm -rf dist && npm run build`
- Check Node.js version: `node -v` (must be 18+)

## Development Tools

```bash
# Lint code
npm run lint

# Type check
npx tsc --noEmit

# Format code
npx prettier --write src/

# Analyze bundle
npm run build -- --visualize
```

## API Integration

The frontend connects to these backend endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | System health status |
| GET | `/api/events` | List events (supports filters) |
| GET | `/api/summary` | Summary statistics |
| POST | `/api/detect` | Run detector on uploaded image |

Example API call:
```typescript
const events = await apiService.getEvents({
  status: 'AIS_UNMATCHED',
  region: 'Gulf of Oman'
})
```

## State Management

Uses Zustand for lightweight state:
```typescript
// Get events
const events = useDashboardStore((s) => s.events)

// Set events
const setEvents = useDashboardStore((s) => s.setEvents)

// Get filtered events
const filtered = useDashboardStore((s) => s.getFilteredEvents())

// Set filter
const setFilter = useDashboardStore((s) => s.setFilter)
```

## Styling

Built with Tailwind CSS and custom utilities:
- Glass morphism effect: `.glass-effect`
- Primary button: `.btn-primary`
- Secondary button: `.btn-secondary`
- Input field: `.input-field`
- Status badges: `.badge-ais-visible`, `.badge-partial`, `.badge-dark`

## Contributing

1. Create a feature branch
2. Make changes
3. Test locally (`npm run dev`)
4. Build production version (`npm run build`)
5. Submit PR with description

## License

Same as parent project (THOR's Smugglers)
