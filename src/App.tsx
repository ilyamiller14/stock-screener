import { Suspense, lazy } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import './App.css'

const Dashboard  = lazy(() => import('./pages/Dashboard'))
const StockDetail = lazy(() => import('./pages/StockDetail'))

function LoadingFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '200px' }}>
      <div className="spinner" />
    </div>
  )
}

function NotFound() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '200px', color: '#8b949e', gap: 16 }}>
      <p style={{ fontSize: 18 }}>Page not found</p>
      <Link to="/" style={{ color: '#58a6ff', fontSize: 14 }}>Back to Dashboard</Link>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <div className="app-header__inner">
            <Link to="/" className="app-header__brand">
              <span className="app-header__logo">▲</span>
              <span className="app-header__name">Russell 2000 Screen</span>
            </Link>
            <div className="app-header__subtitle">Daily technical picks · 3+ month outlook</div>
          </div>
        </header>

        <main className="app-main">
          <Suspense fallback={<LoadingFallback />}>
            <Routes>
              <Route path="/"               element={<Dashboard />} />
              <Route path="/stock/:ticker"  element={<StockDetail />} />
              <Route path="*"               element={<NotFound />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  )
}
