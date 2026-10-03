import { useEffect, useState } from 'react'
import { useDashboardStore } from './store/dashboardStore'
import { Landing } from './components/Landing'
import { Login } from './components/Login'
import { Dashboard } from './components/Dashboard'

const readRoute = () => window.location.hash.replace(/^#\/?/, '')

function App() {
  const [route, setRoute] = useState(readRoute)
  const user = useDashboardStore((s) => s.user)

  useEffect(() => {
    const onChange = () => setRoute(readRoute())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  if (route === 'console') return user ? <Dashboard /> : <Login mode="login" />
  if (route === 'login' || route === 'register') {
    return user ? <Dashboard /> : <Login mode={route} />
  }
  return <Landing />
}

export default App
