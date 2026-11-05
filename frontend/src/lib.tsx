import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react'

const BASE = (import.meta as any).env?.VITE_API_URL || '/api'
export const tokenStore = {
  get: () => localStorage.getItem('ps_token'),
  set: (t: string) => localStorage.setItem('ps_token', t),
  clear: () => localStorage.removeItem('ps_token'),
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: any = {}
  const t = tokenStore.get()
  if (t) headers.Authorization = 'Bearer ' + t
  let body: any
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body) }
  let r: Response
  try { r = await fetch(BASE + path, { method: opts.method || (body ? 'POST' : 'GET'), headers, body }) }
  catch { throw new Error('Cannot reach the server. Is the backend running?') }
  if (r.status === 401 && t) { tokenStore.clear(); location.href = '/login' }
  if (opts.raw) { if (!r.ok) throw new Error('Request failed'); return (await r.blob()) as any }
  const ct = r.headers.get('content-type') || ''
  const data: any = ct.includes('json') ? await r.json() : await r.text()
  if (!r.ok) throw new Error(typeof data === 'object' ? (typeof data.detail === 'string' ? data.detail : 'Request failed') : 'Request failed')
  return data
}

export function useFetch<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(!!path)
  const [error, setError] = useState('')
  const load = useCallback(() => {
    if (!path) { setData(null); setLoading(false); return }
    setLoading(true)
    api<T>(path).then((d) => { setData(d); setError('') }).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [path])
  useEffect(load, [load])
  return { data, loading, error, reload: load, setData }
}

// ---------- auth ----------
type AuthCtx = { user: any; ready: boolean; login: (email: string, password: string) => Promise<void>; logout: () => void; refresh: () => Promise<void> }
const Auth = createContext<AuthCtx>(null as any)
export const useAuth = () => useContext(Auth)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<any>(null)
  const [ready, setReady] = useState(false)
  const refresh = useCallback(async () => {
    if (!tokenStore.get()) { setUser(null); setReady(true); return }
    try { setUser(await api('/auth/me')) } catch { tokenStore.clear(); setUser(null) }
    setReady(true)
  }, [])
  useEffect(() => { refresh() }, [refresh])
  const login = async (email: string, password: string) => {
    const r = await api('/auth/login', { body: { email, password } })
    tokenStore.set(r.access_token); setUser(r.user)
  }
  const logout = () => { tokenStore.clear(); setUser(null); location.href = '/' }
  return <Auth.Provider value={{ user, ready, login, logout, refresh }}>{children}</Auth.Provider>
}

// ---------- toast ----------
const ToastCtx = createContext<(m: string, tone?: 'ok' | 'err') => void>(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<{ m: string; tone: string } | null>(null)
  const show = (m: string, tone: 'ok' | 'err' = 'ok') => { setT({ m, tone }); setTimeout(() => setT(null), 4000) }
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && <div role="status" className={`fixed bottom-4 right-4 z-50 max-w-sm rounded-lg px-4 py-3 text-sm text-white shadow-lg ${t.tone === 'err' ? 'bg-rose-600' : 'bg-slate-900'}`}>{t.m}</div>}
    </ToastCtx.Provider>
  )
}

// run an async action with toast feedback
export function useAction() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<any>, ok?: string) => {
    setBusy(true)
    try { const r = await fn(); if (ok) toast(ok); return r } catch (e: any) { toast(e.message, 'err') } finally { setBusy(false) }
  }
  return { run, busy }
}

// ---------- helpers ----------
export const iso = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
export const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
export const fmtDate = (s: string) => new Date(s + (s.length === 10 ? 'T00:00:00' : '')).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
export const fmtTime = (s: string) => new Date(s).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
export const num = (v: any, d = 1) => (v === null || v === undefined ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }))
export const MEALS = ['breakfast', 'lunch', 'snacks', 'dinner']
export const cap = (s: string) => (s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
export const toLocalInput = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
