import React, { useState } from 'react'
import { apiService } from '../services/api'
import { useDashboardStore } from '../store/dashboardStore'
import { Wordmark, useUtcClock } from './Landing'

export const Login: React.FC<{ mode: 'login' | 'register' }> = ({ mode }) => {
  const login = useDashboardStore((s) => s.login)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isRegister = mode === 'register'
  const clock = useUtcClock()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const session = isRegister
        ? await apiService.register({ name, email, password })
        : await apiService.login({ email, password })
      login(session.user, session.token)
      window.location.hash = '#/console'
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The server could not be reached. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4 sm:px-6">
        <Wordmark />
        <span className="font-mono text-xs text-ink-2">{clock}</span>
      </header>

      <main className="flex flex-1 items-start justify-center px-4 pb-16 pt-8 sm:pt-16">
        <div className="panel w-full max-w-sm p-6 sm:p-8">
          <p className="font-mono text-xs text-ink-3">
            <span className="text-signal">&gt;</span> {isRegister ? 'register --operator' : 'auth --console'}
          </p>
          <h1 className="cursor mt-3 font-mono text-2xl font-bold uppercase tracking-tight">
            {isRegister ? 'Create account' : 'Sign in'}
          </h1>
          <p className="mt-2 text-sm text-ink-2">
            {isRegister
              ? 'An account opens the console: the map, every candidate, and live detection on your own tiles.'
              : 'Sign in to open the console.'}
          </p>

          <form onSubmit={submit} className="mt-8 space-y-5">
            {isRegister && (
              <div>
                <label htmlFor="name" className="label">Name</label>
                <input id="name" className="field" autoComplete="name" required
                  value={name} onChange={(e) => setName(e.target.value)} />
              </div>
            )}
            <div>
              <label htmlFor="email" className="label">Email</label>
              <input id="email" type="email" className="field" autoComplete="email" required
                value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label htmlFor="password" className="label">Password</label>
              <input id="password" type="password" className="field" required
                minLength={isRegister ? 8 : undefined}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                aria-describedby={isRegister ? 'password-hint' : undefined}
                value={password} onChange={(e) => setPassword(e.target.value)} />
              {isRegister && <p id="password-hint" className="mt-1.5 text-sm text-ink-3">At least 8 characters.</p>}
            </div>

            {error && (
              <p role="alert" className="border-l-2 border-unmatched bg-unmatched/10 px-3 py-2 font-mono text-xs text-unmatched">
                {error}
              </p>
            )}

            <button type="submit" disabled={busy} className="btn-primary w-full py-2.5">
              {busy ? (isRegister ? 'Creating account…' : 'Signing in…') : (isRegister ? 'Create account' : 'Sign in')}
            </button>
          </form>

          <p className="mt-6 border-t border-rule pt-5 text-sm text-ink-2">
            {isRegister ? 'Already have an account? ' : 'New here? '}
            <a href={isRegister ? '#/login' : '#/register'} className="font-medium text-signal underline underline-offset-2">
              {isRegister ? 'Sign in' : 'Create an account'}
            </a>
          </p>
        </div>
      </main>
    </div>
  )
}
