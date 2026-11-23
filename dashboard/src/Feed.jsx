import React, { useEffect, useRef, useState } from 'react'
import { ACTOR, POLL_MS, TOKEN, call, notifyFeedChanged, usePoll } from './feedApi'

// The Feed: every finding of every connected repository, with a triage status that is shared with Slack through the engine.
// Live mode shows engine data only. Sample mode (a click on "Use sample data") shows the sample scan, read only.

const STATUS_TABS = [
  ['open', 'Open'],
  ['in_progress', 'In Progress'],
  ['fixed', 'Fixed'],
  ['false_positive', 'False Positive'],
  ['wont_fix', "Won't Fix"]
]
const STATUS_LABEL = Object.fromEntries(STATUS_TABS)
const SETTABLE = ['open', 'in_progress', 'false_positive', 'wont_fix'] // "Fixed" is set by a scan or a verified fix only
const NEEDS_REASON = ['false_positive', 'wont_fix']

const SEVERITY = {
  critical: { rank: 1, label: 'Critical', text: 'text-critical', bar: 'bg-critical' },
  high: { rank: 2, label: 'High', text: 'text-high', bar: 'bg-high' },
  medium: { rank: 3, label: 'Medium', text: 'text-medium', bar: 'bg-medium' },
  low: { rank: 4, label: 'Low', text: 'text-low', bar: 'bg-low' }
}
const PROOF = {
  probed: ['Probed', 'Behaviour confirmed by a live request'],
  observed: ['Observed', 'Seen in live data'],
  static: ['Static', 'Read from files, nothing was run']
}
const HEALTH = {
  healthy: ['Healthy', 'text-accent', 'bg-accent'],
  changed: ['Changed', 'text-medium', 'bg-medium'],
  at_risk: ['At Risk', 'text-critical', 'bg-critical'],
  unknown: ['Unknown', 'text-high', 'bg-high']
}
const EVENT_LABEL = {
  finding_created: 'Found by a scan',
  finding_resolved: 'No longer found by a scan',
  finding_reopened: 'Found again by a scan',
  status_changed: 'Status changed',
  fix_started: 'Fix started',
  fix_verified: 'Fix verified',
  fix_failed: 'Fix failed'
}

const rankOf = (f) => SEVERITY[f.severity]?.rank ?? 99
const bySeverity = (a, b) => rankOf(a) - rankOf(b) || a.human_id.localeCompare(b.human_id)

// ---- small pieces

function Tag({ children, title }) {
  return (
    <span title={title} className="font-mono text-[13px] font-semibold tracking-[0.08em] px-1.5 rounded-[3px] bg-high text-white">
      {children}
    </span>
  )
}

function Label({ children }) {
  return <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted m-0">{children}</h3>
}

function Severity({ value }) {
  const s = SEVERITY[value] || { label: value, text: 'text-muted', bar: 'bg-muted' }
  return (
    <span className={`inline-flex items-center gap-1.5 text-[13px] font-semibold uppercase tracking-[0.06em] ${s.text}`}>
      <span aria-hidden="true" className={`w-1 h-4 rounded-sm ${s.bar}`} />
      {s.label}
    </span>
  )
}

function ProofTag({ value }) {
  const [label, hint] = PROOF[value] || [value, '']
  return (
    <span title={hint} className="text-[13px] text-muted border border-line rounded-[3px] px-1.5">
      {label}
      <span className="sr-only">: {hint}</span>
    </span>
  )
}

const where = (loc) => (loc?.file ? `${loc.file}${loc.line ? `:${loc.line}` : ''}` : loc?.url || '')

// Red banner for a scan that did not look at everything. It is also used on the Findings view of App.jsx.
export function IncompleteBanner({ errors = [], repo = '', failed = '' }) {
  const list = errors.map((e) => `${e.scanner} (${e.kind})`).join(', ')
  return (
    <div role="alert" className="bg-surface border border-line border-l-4 border-l-critical rounded-[6px] px-4 py-2.5 text-[15px] text-critical print:hidden">
      <strong>Scan incomplete: results are partial</strong>
      {repo && <span className="text-ink"> for {repo}</span>}
      {failed ? <span className="text-ink">. The last scan failed: {failed}. The findings below may be out of date.</span> : null}
      {!failed && list ? <span className="text-ink">. Scanners that did not finish: {list}. Findings from the other scanners are shown.</span> : null}
    </div>
  )
}

// Health of one repository: the word is always there, colour is only extra. Reasons on hover and for screen readers.
function HealthPill({ repo }) {
  const h = repo.info
  const [word, text, dot] = HEALTH[h.status] || HEALTH.unknown
  const reasons = [
    ...h.reasons,
    ...(h.failed_streak && !h.reasons.some((r) => r.startsWith('last error')) && h.last_error ? [`last error: ${h.last_error}`] : [])
  ]
  const detail = reasons.length ? reasons.join('. ') : 'No reasons given.'
  const staticOnly = h.reasons.find((r) => /^static checks only/i.test(r))
  return (
    <li className="flex flex-wrap items-center gap-2 text-[14px]">
      <span className="font-mono text-ink">{repo.full_name}</span>
      <span title={detail} className={`inline-flex items-center gap-1.5 font-semibold ${text}`}>
        <span aria-hidden="true" className={`w-2 h-2 rounded-full ${dot}`} />
        {word}
        <span className="sr-only">. Health reasons: {detail}</span>
      </span>
      {staticOnly && <span className="text-muted">{staticOnly[0].toUpperCase() + staticOnly.slice(1)}</span>}
    </li>
  )
}

function SkeletonRows() {
  return Array.from({ length: 5 }, (_, i) => (
    <tr key={i} aria-hidden="true" className="border-b border-line last:border-0">
      {[60, 35, 18].map((w, j) => (
        <td key={j} className="px-4 py-4 align-top">
          <div className="h-4 rounded bg-line motion-safe:animate-pulse" style={{ width: `${w}%` }} />
          {j === 0 && <div className="h-3 mt-2 rounded bg-line motion-safe:animate-pulse w-4/5" />}
        </td>
      ))}
    </tr>
  ))
}

// ---- detail drawer

function Drawer({ record, apiBase, live, onClose, onChanged }) {
  const detail = usePoll(() => call(apiBase, `/findings/${encodeURIComponent(record.human_id)}`), record.human_id, POLL_MS, live)
  const rec = detail.data || record
  const finding = detail.data?.finding || record._finding || null
  const events = detail.data?.events || []
  const canAct = live && Boolean(TOKEN)
  const [picked, setPicked] = useState(null) // the status chosen in the select, null while it follows the finding's own status
  const target = picked ?? rec.status
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState(null) // { ok, text }
  const [fixResult, setFixResult] = useState(null)
  const panel = useRef(null)
  const closeBtn = useRef(null)

  useEffect(() => {
    const opener = document.activeElement
    closeBtn.current?.focus()
    return () => opener?.focus?.()
  }, [])
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') return onClose()
      if (e.key !== 'Tab' || !panel.current) return
      const items = [...panel.current.querySelectorAll('button, select, textarea, input, [href]')].filter((n) => !n.disabled)
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function saveStatus() {
    if (NEEDS_REASON.includes(target) && !reason.trim()) {
      setMessage({ ok: false, text: `${STATUS_LABEL[target]} needs a reason (1 to 300 characters, no personal data).` })
      return
    }
    setBusy('status')
    setMessage(null)
    try {
      await call(apiBase, `/findings/${encodeURIComponent(rec.human_id)}/status`, {
        method: 'PATCH',
        body: { status: target, reason: reason.trim(), actor: ACTOR }
      })
      setMessage({ ok: true, text: `Status is now ${STATUS_LABEL[target]}.` })
      setReason('')
      setPicked(null)
      detail.reload()
      onChanged()
    } catch (e) {
      setMessage({ ok: false, text: e.message })
    } finally {
      setBusy('')
    }
  }

  async function runFix() {
    setBusy('fix')
    setMessage(null)
    setFixResult(null)
    try {
      const out = await call(apiBase, `/findings/${encodeURIComponent(rec.human_id)}/fix?mode=live`, { method: 'POST', body: { actor: ACTOR } })
      setFixResult(out)
      detail.reload()
      onChanged()
    } catch (e) {
      setMessage({ ok: false, text: `Fix failed: ${e.message}` })
    } finally {
      setBusy('')
    }
  }

  const ev = finding?.evidence
  const unchanged = target === rec.status
  return (
    <div className="fixed inset-0 z-40 print:hidden">
      <div className="absolute inset-0 bg-ink/25" onClick={onClose} aria-hidden="true" />
      <aside
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={`Finding ${rec.human_id}`}
        className="absolute inset-y-0 right-0 w-full max-w-[560px] bg-surface border-l border-line shadow-xl overflow-y-auto flex flex-col"
      >
        <div className="px-6 pt-5 pb-4 border-b border-line flex items-start justify-between gap-4">
          <div className="flex flex-col gap-2 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Severity value={rec.severity} />
              <span className="font-mono text-[14px] text-ink">{rec.human_id}</span>
              <ProofTag value={rec.proof} />
            </div>
            <h2 className="font-serif text-[22px] leading-snug font-semibold text-ink m-0">{rec.title}</h2>
            <span className="font-mono text-[13px] text-muted break-all">
              {rec.repo}@{rec.branch || 'default'}
              {where(rec.location) && ` · ${where(rec.location)}`}
            </span>
          </div>
          <button
            ref={closeBtn}
            type="button"
            onClick={onClose}
            className="shrink-0 px-3 py-1.5 rounded-[6px] border border-line text-[15px] text-ink hover:bg-paper cursor-pointer"
          >
            Close
          </button>
        </div>

        <div className="px-6 py-5 flex flex-col gap-6">
          {detail.error && live && (
            <div role="alert" className="text-[15px] text-critical">Could not refresh this finding: {detail.error}</div>
          )}

          <section className="flex flex-col gap-2" aria-label="Status">
            <Label>Status</Label>
            <p className="m-0 text-[15px] text-ink">
              {STATUS_LABEL[rec.status] || rec.status}
              {rec.status_by && <span className="text-muted"> · set by {rec.status_by}</span>}
              {rec.status_reason && <span className="text-muted"> · {rec.status_reason}</span>}
            </p>
            {!live && <p className="m-0 text-[14px] text-muted">Sample data: statuses cannot be changed.</p>}
            {live && !TOKEN && (
              <p className="m-0 text-[14px] text-muted">
                This page has no engine token (VITE_DPDP_TOKEN), so it can show findings but not change them. Change the status in Slack or set the token.
              </p>
            )}
            {canAct && (
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <label className="text-[15px] text-muted" htmlFor="feed-status">Change status to</label>
                  <select
                    id="feed-status"
                    value={target}
                    onChange={(e) => setPicked(e.target.value)}
                    className="px-2 py-1.5 rounded-[6px] border border-line bg-surface text-[15px] text-ink"
                  >
                    {rec.status === 'fixed' && <option value="fixed" disabled>Fixed (set by a scan or a verified fix)</option>}
                    {SETTABLE.map((s) => (
                      <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                    ))}
                  </select>
                </div>
                {NEEDS_REASON.includes(target) && (
                  <>
                    <label className="text-[15px] text-muted" htmlFor="feed-reason">Reason (required, at most 300 characters, no personal data)</label>
                    <textarea
                      id="feed-reason"
                      value={reason}
                      maxLength={300}
                      rows={2}
                      onChange={(e) => setReason(e.target.value)}
                      className="px-3 py-2 rounded-[6px] border border-line bg-surface text-[15px] text-ink"
                    />
                  </>
                )}
                <div>
                  <button
                    type="button"
                    disabled={busy !== '' || unchanged}
                    onClick={saveStatus}
                    className="px-4 py-2 rounded-[6px] bg-accent hover:bg-accent-hover disabled:opacity-60 text-white text-[15px] font-medium cursor-pointer"
                  >
                    {busy === 'status' ? 'Saving...' : 'Update status'}
                  </button>
                </div>
              </div>
            )}
            {message && (
              <p role={message.ok ? 'status' : 'alert'} className={`m-0 text-[15px] ${message.ok ? 'text-accent' : 'text-critical'}`}>{message.text}</p>
            )}
          </section>

          {finding?.severity_reason && (
            <section className="flex flex-col gap-1.5">
              <Label>Why this severity</Label>
              <p className="m-0 text-[15px] text-ink">{finding.severity_reason}</p>
            </section>
          )}

          <section className="flex flex-col gap-1.5">
            <Label>What we found</Label>
            <p className="m-0 text-[15px] text-ink">{finding?.explanation || rec.explanation}</p>
          </section>

          {finding?.clauses?.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <Label>Law</Label>
              <ul className="m-0 pl-0 list-none flex flex-col gap-1">
                {finding.clauses.map((c) => (
                  <li key={c.ref} className="text-[15px] text-ink">
                    <span className="font-mono text-[14px] font-medium">{c.ref}</span>
                    <span className="text-muted"> · {c.note}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {ev && (
            <section className="flex flex-col gap-1.5">
              <Label>Evidence</Label>
              <div className="border border-line rounded-[6px] overflow-hidden">
                <div className="px-3 py-1.5 bg-paper border-b border-line font-mono text-[13px] text-muted break-all">
                  {where(rec.location) || ev.kind}
                </div>
                <div className="px-3 py-2 text-[15px] text-ink">{ev.summary}</div>
                {ev.masked_sample && <pre className="m-0 px-3 py-2 border-t border-line font-mono text-[14px] text-ink whitespace-pre-wrap break-all">{ev.masked_sample}</pre>}
              </div>
            </section>
          )}

          {finding?.recommendation && (
            <section className="flex flex-col gap-1.5">
              <Label>Recommended fix</Label>
              <p className="m-0 text-[15px] text-ink">{finding.recommendation}</p>
            </section>
          )}

          {live && rec.fix_available && rec.status !== 'fixed' && TOKEN && (
            <section className="flex flex-col gap-2" aria-label="Fix and verify">
              <Label>Verified fix</Label>
              <p className="m-0 text-[14px] text-muted">
                Patches a sandbox copy of a fresh checkout, re-scans it and runs the repo's tests. Only for repositories the engine may run code from.
              </p>
              <div>
                <button
                  type="button"
                  disabled={busy !== ''}
                  onClick={runFix}
                  className="px-4 py-2 rounded-[6px] border border-line bg-surface hover:bg-paper disabled:opacity-60 text-ink text-[15px] font-medium cursor-pointer"
                >
                  {busy === 'fix' ? 'Running the fix in a sandbox...' : 'Fix and verify'}
                </button>
              </div>
              {fixResult && (
                <div role="status" className="flex flex-col gap-1.5 text-[15px]">
                  <span className={`font-semibold ${fixResult.finding.fix.verified ? 'text-accent' : 'text-critical'}`}>
                    {fixResult.finding.fix.verified ? 'VERIFIED' : 'NOT VERIFIED'}
                    {fixResult.mode === 'cached_golden' && <> <Tag title={fixResult.fallback_reason || 'Replay of a saved verified run'}>CACHED</Tag></>}
                  </span>
                  <span className="text-muted">
                    Re-scan {fixResult.finding.fix.rescan_passed ? 'passed' : 'did not pass'}, tests {fixResult.finding.fix.tests_passed ? 'passed' : 'did not pass'}.
                    {fixResult.fallback_reason && ` ${fixResult.fallback_reason}`}
                  </span>
                  {fixResult.finding.fix.diff && (
                    <pre className="m-0 p-3 border border-line rounded-[6px] bg-paper font-mono text-[13px] overflow-x-auto whitespace-pre">{fixResult.finding.fix.diff}</pre>
                  )}
                </div>
              )}
            </section>
          )}

          <section className="flex flex-col gap-2" aria-label="Timeline">
            <Label>Timeline</Label>
            {events.length === 0 ? (
              <p className="m-0 text-[15px] text-muted">{live ? (detail.loading ? 'Loading...' : 'No events yet.') : 'Sample data has no events.'}</p>
            ) : (
              <ol className="m-0 p-0 list-none flex flex-col gap-2">
                {[...events].reverse().map((e) => (
                  <li key={e.id} className="text-[15px] text-ink">
                    {EVENT_LABEL[e.type] || e.type}
                    {e.result && <span className="text-muted"> · {e.result}</span>}
                    <div className="font-mono text-[13px] text-muted">
                      {e.actor} · {new Date(e.ts).toLocaleString([], { hour12: false })}{e.scan_id ? ` · ${e.scan_id}` : ''}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </aside>
    </div>
  )
}

// ---- sample mode

function sampleRecords(scan) {
  return (scan.findings || []).map((f, i) => ({
    human_id: `DPDP-${String(i + 1).padStart(3, '0')}`,
    repo: 'sample/tutornest',
    branch: 'main',
    check: f.check,
    severity: f.severity,
    title: f.title,
    layer: f.layer,
    proof: f.proof || 'static',
    status: f.status === 'verified_fixed' ? 'fixed' : 'open',
    status_reason: '',
    status_by: '',
    location: f.evidence?.location || {},
    fix_available: false,
    explanation: f.explanation,
    _finding: f
  }))
}

// ---- the view

export default function Feed({ apiBase, sampleMode, sampleScan }) {
  const [repoId, setRepoId] = useState('')
  const [status, setStatus] = useState('open')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [opened, setOpened] = useState(null) // the record of the row that was clicked: it stays open after its status moves it out of this tab
  const live = !sampleMode

  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 250)
    return () => clearTimeout(t)
  }, [qInput])

  const query = new URLSearchParams({ limit: '500', ...(repoId && { repo_id: repoId }), ...(status && { status }), ...(q && { q }) }).toString()
  const findings = usePoll(() => call(apiBase, `/findings?${query}`), `findings?${query}`, POLL_MS, live)
  const repos = usePoll(async () => {
    const list = await call(apiBase, '/repos')
    return Promise.all(
      list.map(async (r) => {
        const [info, hist] = await Promise.all([call(apiBase, `/repos/${r.id}/health`), call(apiBase, `/repos/${r.id}/history?limit=1`)])
        return { ...r, info, last: hist[0] || null }
      })
    )
  }, 'repos', POLL_MS, live)

  // Sample mode: the same shapes, built from the sample scan, no polling and no changes.
  const sample = sampleRecords(sampleScan || {})
  const sampleView = sample.filter((r) => r.status === status && (!q || `${r.human_id} ${r.title} ${r.check}`.toLowerCase().includes(q.toLowerCase())))
  const sampleCounts = Object.fromEntries(STATUS_TABS.map(([k]) => [k, sample.filter((r) => r.status === k).length]))

  const items = live ? [...(findings.data?.items || [])].sort(bySeverity) : [...sampleView].sort(bySeverity)
  const counts = live ? findings.data?.counts_by_status || {} : sampleCounts
  const repoList = live ? repos.data || [] : []
  const inScope = repoList.filter((r) => !repoId || String(r.id) === repoId)
  const broken = inScope.filter((r) => r.last && r.last.status !== 'complete')
  const everything = STATUS_TABS.reduce((n, [k]) => n + (counts[k] || 0), 0)
  const loading = live && findings.loading && !findings.data

  function reloadAll() {
    findings.reload()
    repos.reload()
    notifyFeedChanged()
  }

  return (
    <div className="flex flex-col gap-4">
      {live && broken.map((r) => (
        <IncompleteBanner
          key={r.id}
          repo={r.full_name}
          errors={r.last.status === 'incomplete' ? r.last.errors : []}
          failed={r.last.status === 'failed' ? r.last.errors?.[0]?.message || 'no reason was recorded' : ''}
        />
      ))}
      {live && findings.error && findings.data && (
        <div role="alert" className="bg-surface border border-line border-l-4 border-l-high rounded-[6px] px-4 py-2.5 text-[15px] text-high">
          Showing the last answer from the engine. The latest refresh failed: {findings.error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <label className="sr-only" htmlFor="feed-repo">Repository</label>
        <select
          id="feed-repo"
          value={repoId}
          disabled={!live}
          onChange={(e) => setRepoId(e.target.value)}
          className="px-3 py-2 rounded-[6px] border border-line bg-surface text-[15px] text-ink"
        >
          <option value="">All repositories</option>
          {repoList.map((r) => (
            <option key={r.id} value={r.id}>{r.full_name}</option>
          ))}
        </select>
        <label className="sr-only" htmlFor="feed-search">Search findings</label>
        <input
          id="feed-search"
          type="search"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Search by ID, title or file"
          className="flex-1 min-w-[220px] max-w-[420px] px-3 py-2 rounded-[6px] border border-line bg-surface text-[15px] text-ink"
        />
      </div>

      {live && inScope.length > 0 && (
        <ul aria-label="Repository health" className="m-0 p-0 list-none flex flex-col gap-1">
          {inScope.map((r) => <HealthPill key={r.id} repo={r} />)}
        </ul>
      )}
      {!live && <p className="m-0 text-[14px] text-muted">Sample data. Connect a repository from Slack with /dpdp connect to see real findings.</p>}

      <div role="tablist" aria-label="Status" className="flex flex-wrap gap-1 border-b border-line">
        {STATUS_TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={status === key}
            onClick={() => setStatus(key)}
            className={`px-3 py-2 text-[15px] cursor-pointer border-b-2 -mb-px ${
              status === key ? 'border-accent text-ink font-semibold' : 'border-transparent text-muted hover:text-ink font-medium'
            }`}
          >
            {label}{' '}
            <span className="ml-1 font-mono text-[14px] tabular">{counts[key] ?? 0}</span>
          </button>
        ))}
      </div>

      {live && findings.error && !findings.data ? (
        <div role="alert" className="bg-surface border border-line border-l-4 border-l-critical rounded-[6px] p-6 flex flex-col gap-3">
          <span className="font-serif text-[20px] font-semibold text-ink">The Feed could not load findings</span>
          <span className="text-[15px] text-critical">{findings.error}</span>
          <div>
            <button type="button" onClick={reloadAll} className="px-4 py-2 rounded-[6px] border border-line bg-surface hover:bg-paper text-[15px] font-medium text-ink cursor-pointer">
              Try again
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-surface border border-line rounded-[6px] overflow-x-auto" aria-busy={loading}>
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-[13px] uppercase tracking-[0.06em] text-muted">
                <th scope="col" className="px-4 py-2.5 font-semibold w-[52%]">Finding</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Location</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && <SkeletonRows />}
              {!loading && items.map((r) => (
                <tr
                  key={r.human_id}
                  onClick={() => setOpened(r)}
                  className="border-b border-line last:border-0 hover:bg-paper cursor-pointer align-top"
                >
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Severity value={r.severity} />
                      <span className="font-mono text-[14px] text-muted">{r.human_id}</span>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setOpened(r) }}
                      className="mt-1 p-0 bg-transparent border-0 text-left text-[16px] font-medium text-ink hover:underline underline-offset-4 cursor-pointer"
                    >
                      {r.title}
                    </button>
                    {r.explanation && <p className="m-0 mt-0.5 text-[14px] text-muted line-clamp-1">{r.explanation}</p>}
                  </td>
                  <td className="px-4 py-3 text-[14px]">
                    <div className="font-mono text-ink break-all">{where(r.location) || '-'}</div>
                    <div className="font-mono text-muted">{r.repo}@{r.branch || 'default'}</div>
                  </td>
                  <td className="px-4 py-3 text-[15px] text-ink whitespace-nowrap">
                    {STATUS_LABEL[r.status] || r.status}
                    {r.slack && <span className="sr-only"> (linked to a Slack message)</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && items.length === 0 && (
            <div className="px-6 py-10 text-center text-[15px] text-muted">
              {live && everything === 0 && repoList.length === 0 && !q ? (
                <>
                  <p className="m-0 font-serif text-[20px] text-ink">No findings yet.</p>
                  <p className="m-0 mt-1">Connect a repository from Slack with <code>/dpdp connect</code></p>
                </>
              ) : (
                <p className="m-0">No findings in {STATUS_LABEL[status]}{q ? ` that match "${q}"` : ''}{repoId ? ' for this repository' : ''}.</p>
              )}
            </div>
          )}
        </div>
      )}

      {opened && <Drawer key={opened.human_id} record={opened} apiBase={apiBase} live={live} onClose={() => setOpened(null)} onChanged={reloadAll} />}
    </div>
  )
}
