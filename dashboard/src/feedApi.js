// Engine calls and polling for the Feed (Feed.jsx) and the rail count (App.jsx).
import { useCallback, useEffect, useRef, useState } from 'react'

// VITE_DPDP_TOKEN is the engine's X-DPDP-Token. It is bundled into the page, so it is for the localhost demo only and not a secret.
export const TOKEN = import.meta.env.VITE_DPDP_TOKEN || ''
export const POLL_MS = 5000 // no websockets: the Feed polls, so a change made in Slack shows up within one interval
export const ACTOR = 'dashboard'

// The Feed tells the rail to refresh its count right after a change, instead of waiting for the next poll.
const CHANGED = 'dpdp-feed-changed'
export const notifyFeedChanged = () => window.dispatchEvent(new Event(CHANGED))

export async function call(apiBase, path, { method = 'GET', body } = {}) {
  let res
  try {
    res = await fetch(apiBase + path, {
      method,
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(method !== 'GET' && TOKEN ? { 'X-DPDP-Token': TOKEN } : {}) },
      body: body ? JSON.stringify(body) : undefined
    })
  } catch {
    throw new Error(`Could not reach the engine at ${apiBase}`)
  }
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json()).detail
    } catch {
      /* the engine's own text is only there for JSON answers */
    }
    throw new Error(detail || `The engine answered ${res.status}`)
  }
  return res.json()
}

// Run `load` now and then every `ms`, one at a time. The old data stays on screen while a new answer is on its way.
export function usePoll(load, key, ms = POLL_MS, enabled = true) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [bump, setBump] = useState(0)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load // after the render, so a poll always runs the latest closure
  })
  useEffect(() => {
    if (!enabled) return undefined
    let dead = false
    let timer
    const run = async () => {
      try {
        const data = await loadRef.current()
        if (!dead) setState({ data, error: null, loading: false })
      } catch (e) {
        if (!dead) setState((s) => ({ data: s.data, error: e.message, loading: false }))
      }
      if (!dead) timer = setTimeout(run, ms)
    }
    run()
    return () => {
      dead = true
      clearTimeout(timer)
    }
  }, [key, ms, enabled, bump])
  const reload = useCallback(() => setBump((n) => n + 1), [])
  return { ...state, reload }
}

// The number next to "Feed" in the rail. One small request, only while the engine is there and the app is live.
export function useOpenCount(apiBase, enabled) {
  const { data, reload } = usePoll(() => call(apiBase, '/findings?limit=1'), 'open-count', POLL_MS, enabled)
  useEffect(() => {
    window.addEventListener(CHANGED, reload)
    return () => window.removeEventListener(CHANGED, reload)
  }, [reload])
  return data?.counts_by_status?.open ?? null
}

