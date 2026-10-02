# Dark STS Detector - React Frontend

High-end, production-grade React dashboard for detecting dark ship-to-ship transfers using Sentinel-1 SAR imagery and AIS data.

## Features

- **Interactive Map** - Real-time visualization of detected STS events with Leaflet
- **Analytics Dashboard** - Comprehensive charts and statistics
- **Event Management** - Detailed event inspection with filterable table
- **Status Monitoring** - Health checks and system status
- **Responsive Design** - Works on desktop, tablet, and mobile
- **Dark Mode** - Built with modern dark theme using Tailwind CSS

## Architecture

```
frontend/
  ├── src/
  │   ├── components/       # React components
  │   ├── services/         # API client
  │   ├── store/            # Zustand state management
  │   ├── App.tsx          # Main app component
  │   ├── main.tsx         # Entry point
  │   └── index.css        # Global styles
  ├── package.json         # Dependencies
  ├── vite.config.ts       # Vite configuration
  ├── tailwind.config.js   # Tailwind theme
  └── index.html           # HTML template
```

## Installation

```bash
cd webapp/frontend
npm install
```

## Development

```bash
npm run dev
```

The dev server will start at `http://localhost:3000` and proxy API requests to `http://localhost:8000`.

## Build

```bash
npm run build
```

## Environment

The frontend expects the backend API at `/api/`. In development, configure this in `vite.config.ts`:

```typescript
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true
  }
}
```

## API Endpoints

- `GET /api/health` - System health status
- `GET /api/events` - List STS events (filterable)
- `GET /api/summary` - Summary statistics
- `POST /api/detect` - Run detector on uploaded image

## Components

### Dashboard
Main page with maps, charts, and event table.

### Map
Interactive Leaflet map showing event locations with clustering.

### Charts
- Status distribution (pie chart)
- Confidence distribution (bar chart)
- Time series trends (line chart)

### EventTable
Sortable, filterable table of recent events with inline detail modal.

### FilterPanel
Filters by status, region, and confidence threshold.

## State Management

Uses Zustand for lightweight state:
- Event list and filtering
- Selected event detail
- Filter state
- Loading/error states

## Styling

Tailwind CSS with custom theme:
- **Colors**: Ocean blues, slate grays, danger reds
- **Glass morphism**: Frosted glass effect for cards
- **Gradients**: Modern gradient backgrounds
- **Animations**: Smooth transitions and pulse effects

## Performance

- Code splitting via Vite
- Lazy loading for heavy components
- Efficient re-renders with Zustand
- Optimized bundle size (~250KB gzipped)

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## Deployment

### Docker
```dockerfile
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Vercel
```bash
vercel deploy
```

## License

Same as parent project
