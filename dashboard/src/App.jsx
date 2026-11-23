import React, { useState, useEffect } from 'react'
import sampleScan from './sample-scan.json'

// API & Environment Constants
const API_BASE = 'http://localhost:8100'

// Severity rank for sorting: critical first
const SEVERITY_ORDER = {
  critical: 1,
  high: 2,
  medium: 3,
  low: 4
}

const SEVERITY_WEIGHTS = {
  critical: 20,
  high: 10,
  medium: 5,
  low: 2
}

// Severity is always shown with its word, never colour alone. Full class names so Tailwind finds them.
const SEVERITY_STYLES = {
  critical: { bar: 'bg-critical', text: 'text-critical', label: 'Critical' },
  high: { bar: 'bg-high', text: 'text-high', label: 'High' },
  medium: { bar: 'bg-medium', text: 'text-medium', label: 'Medium' },
  low: { bar: 'bg-low', text: 'text-low', label: 'Low' }
}

function readiness(score) {
  if (score === null) return 'No scan yet'
  return score < 50 ? 'Not ready' : score < 80 ? 'Partly ready' : 'Ready for review'
}

// Brand mark: a ring with a notch and a centre point. Original, drawn by hand; public/favicon.svg is the same shape.
function LogoMark({ className }) {
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="11" stroke="currentColor" strokeWidth="3.5" strokeDasharray="56 13.1" transform="rotate(-12 16 16)" />
      <circle cx="16" cy="16" r="3.5" fill="currentColor" />
    </svg>
  )
}

// Real time since `since` (a performance.now() value), redrawn every 100 ms.
function Elapsed({ since }) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    const id = setInterval(() => setNow(performance.now()), 100)
    return () => clearInterval(id)
  }, [])
  return <span className="tabular">{secs(Math.max(0, now - since))}</span>
}

// Done, current or pending marker for the fix steps and the scan layers.
function StepMarker({ state }) {
  if (state === 'done')
    return (
      <svg aria-hidden="true" className="w-5 h-5 text-accent shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
      </svg>
    )
  if (state === 'current')
    return (
      <span aria-hidden="true" className="w-5 h-5 rounded-full border-2 border-accent grid place-items-center shrink-0">
        <span className="w-2 h-2 rounded-full bg-accent" />
      </span>
    )
  return <span aria-hidden="true" className="w-5 h-5 rounded-full border border-line shrink-0" />
}

// One tag style for state labels (CACHED, SAMPLE).
function Tag({ children }) {
  return (
    <span className="font-mono text-[13px] font-semibold tracking-[0.08em] px-1.5 rounded-[3px] bg-high text-white">{children}</span>
  )
}

// Small uppercase heading used for every block in the detail panel.
function Label({ children }) {
  return <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted m-0">{children}</h3>
}

// Fix phases in the order the engine measures them (verification.steps in the fix response).
const FIX_STEPS = [
  ['copy', 'Copy app to a sandbox'],
  ['patch', 'Apply patch'],
  ['start', 'Start the patched app'],
  ['rescan', 'Re-scan the patched app'],
  ['tests', "Run the app's tests"]
]

// Visual pacing only: a step stays on screen at least this long so a person can read it. Durations shown are the engine's.
const MIN_STEP_MS = 600
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const secs = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`)

// What the engine is doing, by scanner name. The engine reports { step, done, total } while a scan runs.
const SCAN_STEP_LABELS = {
  api_scan: 'Testing the API for exposed personal data',
  idor_probe: 'Testing API access control (IDOR)',
  db_scan: 'Inspecting the database for plaintext personal data',
  log_scan: 'Scanning source code for personal data in logs',
  erasure_scan: 'Checking that deletion really erases data',
  children_scan: 'Testing signup for under-18 users',
  contact_scan: 'Looking for a DPO or grievance contact',
  browser_scan: 'Auditing the signup page in a browser',
  notice_drift: 'Comparing the privacy notice with what runs'
}

const SEVERITIES = ['critical', 'high', 'medium', 'low']

// Scan steps in the engine's order (runner.SCANNERS plus notice_drift); progress.done counts finished steps.
const SCAN_ORDER = Object.keys(SCAN_STEP_LABELS)
const SCAN_LAYERS = [
  ['API', ['api_scan', 'idor_probe', 'children_scan']],
  ['Database', ['db_scan', 'erasure_scan']],
  ['Code', ['log_scan']],
  ['Browser', ['browser_scan']],
  ['Notice', ['contact_scan', 'notice_drift']]
]

// Measured time of a layer: the sum of its finished steps (progress.steps_ms from the engine).
function layerMs(steps, progress) {
  const done = (progress?.steps_ms || []).filter((x) => steps.includes(x.step))
  return done.length ? done.reduce((n, x) => n + x.ms, 0) : null
}

function layerState(steps, progress) {
  const done = progress?.done ?? 0
  if (steps.every((st) => SCAN_ORDER.indexOf(st) < done)) return 'done'
  return steps.includes(progress?.step) ? 'current' : 'pending'
}

// Data Flow columns after Notice. Browser = a third-party request from the page (request: entries).
const DRIFT_LAYERS = [['db', 'Database'], ['api', 'API'], ['request', 'Browser']]
const LANE_COLS = [['notice', 'Notice'], ...DRIFT_LAYERS]

const LAYER_NAMES = { db: 'Database', code: 'Code', api: 'API', browser: 'Browser', notice: 'Notice' }

// What the page shows before any scan. Never sample data.
const EMPTY_SCAN = { target: '', scanned_at: null, score: null, counts: null, findings: [], notice_drift: null }

// Paths are relative to the repo root: the engine resolves them and rejects anything outside it.
const SCAN_REQUEST = {
  target_url: 'http://localhost:8000',
  repo_path: 'target-app/backend',
  db_path: 'target-app/backend/demo.db'
}

async function engineError(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    /* not JSON */
  }
  if (body?.detail) return new Error(`${body.error ? `${body.error}: ` : ''}${body.detail}`)
  return new Error(`Engine returned HTTP ${res.status}`)
}

// Start a scan on the engine and wait for it. Throws an Error with the engine's own text on any failure.
async function runEngineScan(onProgress) {
  let start
  try {
    start = await fetch(`${API_BASE}/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(SCAN_REQUEST)
    })
  } catch {
    throw new Error(`Could not reach the engine at ${API_BASE}`)
  }
  if (!start.ok) throw await engineError(start)
  const { scan_id } = await start.json()

  for (let attempt = 0; attempt < 50; attempt++) {
    await new Promise((r) => setTimeout(r, 300))
    const res = await fetch(`${API_BASE}/scan/${scan_id}`)
    if (!res.ok) throw await engineError(res)
    const result = await res.json()
    if (result.status !== 'running') {
      let steps = null
      try {
        const t = await fetch(`${API_BASE}/scan/${scan_id}/timings`)
        if (t.ok) steps = (await t.json()).steps
      } catch {
        /* timings are optional: the result stands without them */
      }
      return { result, steps }
    }
    await onProgress(result)
  }
  throw new Error('The scan did not finish within 15 seconds')
}

function countOpen(findings) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 }
  findings.forEach((f) => {
    if (f.status === 'open') counts[f.severity] += 1
  })
  return counts
}

// Ask the engine to fix and verify one finding. Throws an Error with the engine's own text on failure.
async function requestFix(scanId, findingId, mode = 'live') {
  let res
  try {
    res = await fetch(
      `${API_BASE}/findings/${encodeURIComponent(findingId)}/fix?scan_id=${encodeURIComponent(scanId)}&mode=${mode}`,
      { method: 'POST' }
    )
  } catch {
    throw new Error(`Could not reach the engine at ${API_BASE}`)
  }
  if (!res.ok) throw await engineError(res)
  return res.json()
}

function formatLocation(loc) {
  if (!loc) return null
  if (loc.file) return `${loc.file}${loc.line ? `:${loc.line}` : ''}`
  if (loc.url) return loc.url
  if (loc.table) return `${loc.table}${loc.column ? `.${loc.column}` : ''}`
  return null
}

function DiffViewer({ diffText }) {
  if (!diffText) return null
  const lines = diffText.split('\n')

  return (
    <div className="bg-surface border border-line rounded-[6px] overflow-x-auto text-[14px] font-mono py-2 leading-relaxed">
      {lines.map((line, idx) => {
        let lineStyle = 'text-ink'
        let lineBg = ''

        if (line.startsWith('---') || line.startsWith('+++')) {
          lineStyle = 'text-muted'
        } else if (line.startsWith('@@')) {
          lineStyle = 'text-muted'
          lineBg = 'bg-paper'
        } else if (line.startsWith('+')) {
          lineBg = 'bg-[#E3F0EC]'
        } else if (line.startsWith('-')) {
          lineBg = 'bg-[#FBE9E7]'
        }

        return (
          <div key={idx} className={`px-3 whitespace-pre-wrap break-words ${lineStyle} ${lineBg}`}>
            {line || ' '}
          </div>
        )
      })}
    </div>
  )
}

function StatusBadge({ label, passed }) {
  const isPassed = passed === true
  const isFailed = passed === false

  return (
    <span
      className={`inline-flex items-center gap-2 text-[15px] font-medium ${
        isPassed ? 'text-accent' : isFailed ? 'text-critical' : 'text-muted'
      }`}
    >
      {isPassed ? (
        <svg aria-hidden="true" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
        </svg>
      ) : isFailed ? (
        <svg aria-hidden="true" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
        </svg>
      ) : (
        <span aria-hidden="true" className="w-2 h-2 rounded-full bg-muted" />
      )}
      {label}
    </span>
  )
}

export default function App() {
  const [scanData, setScanData] = useState(EMPTY_SCAN)
  const [activeTab, setActiveTab] = useState('findings')

  // Real Engine & Mock Mode States
  const [sampleMode, setSampleMode] = useState(false) // only a click on "Use sample data" turns this on
  const [engineConnected, setEngineConnected] = useState(null) // null = checking, true, false
  const [scanError, setScanError] = useState(null)
  const [isScanning, setIsScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState(null) // { step, done, total } from the engine, null before the first answer

  // Fix workflow states
  const [fixingFindingId, setFixingFindingId] = useState(null)
  const [currentStepIndex, setCurrentStepIndex] = useState(-1) // -1 while waiting for the engine, then the replayed step
  const [fixStartedAt, setFixStartedAt] = useState(null)
  const [fixLog, setFixLog] = useState(null) // verification log of the run being shown
  const [scanStartedAt, setScanStartedAt] = useState(null)
  const [animatedScore, setAnimatedScore] = useState(null)
  const [scoreHistory, setScoreHistory] = useState(null)
  const [fixError, setFixError] = useState(null)
  const [fixMeta, setFixMeta] = useState({}) // finding id -> { mode, fallbackReason } for results of this session
  const [copyState, setCopyState] = useState(null) // { id, ok } after a click on "Copy diff"

  // Check Engine health on mount
  useEffect(() => {
    checkEngineHealth()
  }, [])

  async function checkEngineHealth() {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(1200) })
      setEngineConnected(res.ok)
    } catch {
      setEngineConnected(false)
    }
  }

  // Sort findings: critical first, then high, medium, low
  const sortedFindings = [...(scanData.findings || [])].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] || 99) - (SEVERITY_ORDER[b.severity] || 99)
  )

  const [selectedFindingId, setSelectedFindingId] = useState(
    sortedFindings.length > 0 ? sortedFindings[0].id : null
  )

  const hasScan = Boolean(scanData.scan_id)

  const selectedFinding = sortedFindings.find((f) => f.id === selectedFindingId) || sortedFindings[0]

  // Keyboard navigation: ArrowUp and ArrowDown navigate the list
  useEffect(() => {
    function handleKeyDown(e) {
      if (!sortedFindings.length || fixingFindingId !== null || isScanning) return
      const currentIndex = sortedFindings.findIndex((f) => f.id === selectedFindingId)

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        const nextIndex = (currentIndex + 1) % sortedFindings.length
        setSelectedFindingId(sortedFindings[nextIndex].id)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        const prevIndex = (currentIndex - 1 + sortedFindings.length) % sortedFindings.length
        setSelectedFindingId(sortedFindings[prevIndex].id)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedFindingId, sortedFindings, fixingFindingId, isScanning])

  const handleUseSample = () => {
    setSampleMode(true)
    setScanError(null)
    setFixError(null)
    setFixMeta({})
    setScanData(sampleScan)
    setAnimatedScore(sampleScan.score)
    setScoreHistory(null)
    setSelectedFindingId(sampleScan.findings[0]?.id ?? null)
  }

  // Leave sample mode: clear the sample result and check the engine again.
  const handleBackToLive = () => {
    setSampleMode(false)
    setScanData(EMPTY_SCAN)
    setAnimatedScore(null)
    setScoreHistory(null)
    setFixMeta({})
    setFixError(null)
    setScanError(null)
    setSelectedFindingId(null)
    setEngineConnected(null)
    checkEngineHealth()
  }

  // Run scan: real engine by default. Any error is shown in a red banner, never replaced by sample data.
  const handleRunScan = async () => {
    setIsScanning(true)
    setScanProgress(null)
    setScanError(null)
    setFixError(null)
    setFixMeta({})

    setScanStartedAt(performance.now())

    // Each new step stays visible for MIN_STEP_MS; a newer snapshot of the same step shows at once.
    let shownAt = 0
    let shownStep = null
    const show = async (p) => {
      const wait = shownAt + MIN_STEP_MS - performance.now()
      if (p.step !== shownStep && wait > 0) await sleep(wait)
      if (p.step !== shownStep) shownAt = performance.now()
      shownStep = p.step
      setScanProgress(p)
    }

    try {
      if (sampleMode) {
        handleUseSample()
      } else {
        const { result, steps } = await runEngineScan(show)
        if (steps) await show({ step: null, done: steps.length, total: steps.length, steps_ms: steps }) // every layer done, measured
        await sleep(Math.max(0, shownAt + MIN_STEP_MS - performance.now()))
        setEngineConnected(true)
        setScanData(result)
        setAnimatedScore(result.score)
        setScoreHistory(null)
        setSelectedFindingId(result.findings?.[0]?.id ?? null)
      }
      setActiveTab('findings')
    } catch (e) {
      setScanError(e.message)
    } finally {
      setIsScanning(false)
    }
  }

  function animateScore(from, to) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setAnimatedScore(to)
      return
    }
    const startTime = performance.now()
    function animate(now) {
      const progress = Math.min(1, (now - startTime) / 800)
      const eased = 1 - (1 - progress) ** 3 // ease-out
      setAnimatedScore(Math.round(from + (to - from) * eased))
      if (progress < 1) requestAnimationFrame(animate)
    }
    requestAnimationFrame(animate)
  }

  // Fix and verify: sample mode simulates it, live mode asks the engine.
  // mode 'cached' replays the saved verified result on purpose (labelled), 'live' runs the real sandbox.
  const handleFixAndVerify = (finding, mode = 'live') => {
    if (!finding || fixingFindingId !== null) return
    setFixError(null)
    if (sampleMode) finishFix(finding) // simulated and labelled: no steps are shown because none ran
    else runEngineFix(finding, mode)
  }

  // While the engine works only the real elapsed time is shown. When it answers, its measured steps are
  // replayed, each visible for MIN_STEP_MS. A cached result has no live run, so nothing is replayed.
  const runEngineFix = async (finding, mode) => {
    setFixingFindingId(finding.id)
    setCurrentStepIndex(-1)
    setFixLog(null)
    setFixStartedAt(performance.now())
    try {
      const {
        finding: updated,
        score_before,
        score_after,
        mode: usedMode,
        fallback_reason,
        verification
      } = await requestFix(scanData.scan_id, finding.id, mode)
      const log = usedMode === 'live' ? verification : null
      if (log?.steps) {
        setFixLog(log)
        for (let i = 0; i <= FIX_STEPS.length; i++) {
          setCurrentStepIndex(i)
          if (i < FIX_STEPS.length) await sleep(MIN_STEP_MS)
        }
      }
      setScanData((prev) => {
        const findings = prev.findings.map((f) => (f.id === updated.id ? updated : f))
        return { ...prev, findings, score: score_after, counts: countOpen(findings) }
      })
      setFixMeta((prev) => ({ ...prev, [updated.id]: { mode: usedMode, fallbackReason: fallback_reason, verification: log } }))
      if (updated.status === 'verified_fixed') {
        animateScore(score_before, score_after)
        setScoreHistory((prev) => ({ before: prev?.before ?? score_before, after: score_after }))
      }
    } catch (e) {
      setFixError(e.message) // the finding stays open
    } finally {
      setFixingFindingId(null)
      setCurrentStepIndex(-1)
      setFixLog(null)
    }
  }

  const finishFix = (finding) => {
    const scoreBefore = scanData.score
    const scoreAfter = Math.min(100, scoreBefore + (SEVERITY_WEIGHTS[finding.severity] || 10))
    animateScore(scoreBefore, scoreAfter)

    setScanData((prev) => {
      const updatedFindings = prev.findings.map((f) =>
        f.id === finding.id
          ? {
              ...f,
              status: 'verified_fixed',
              fix: {
                ...f.fix,
                verified: true,
                rescan_passed: true,
                tests_passed: true,
                score_before: scoreBefore,
                score_after: scoreAfter
              }
            }
          : f
      )
      return { ...prev, score: scoreAfter, counts: countOpen(updatedFindings), findings: updatedFindings }
    })

    setFixMeta((prev) => ({ ...prev, [finding.id]: { mode: 'simulated', fallbackReason: null } }))
    setScoreHistory({ before: scoreBefore, after: scoreAfter })
    setFixingFindingId(null)
    setCurrentStepIndex(-1)
  }

  const copyDiff = async (finding) => {
    let ok = true
    try {
      await navigator.clipboard.writeText(finding.fix.diff)
    } catch {
      ok = false
    }
    setCopyState({ id: finding.id, ok })
    setTimeout(() => setCopyState(null), 2000)
  }

  const downloadPatch = (finding) => {
    const url = URL.createObjectURL(new Blob([finding.fix.diff], { type: 'text/x-diff' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${finding.id}-${finding.check}.patch`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const handleResetDemo = () => {
    setScanData(sampleScan)
    setAnimatedScore(sampleScan.score)
    setScoreHistory(null)
    setFixMeta({})
    setFixError(null)
    setFixingFindingId(null)
    setCurrentStepIndex(-1)
  }

  // Live scan: open the engine's report in a new tab. Sample mode (or no scan yet): print this page.
  const handleExportReport = () => {
    if (!sampleMode && scanData.scan_id) {
      window.open(`${API_BASE}/report/${encodeURIComponent(scanData.scan_id)}`, '_blank', 'noopener')
    } else {
      window.print()
    }
  }

  const score = animatedScore
  const openTotal = SEVERITIES.reduce((n, sev) => n + (scanData.counts?.[sev] || 0), 0)

  // Notice drift computed properties
  const drift = scanData.notice_drift || { declared: [], observed: [], undeclared: [] }
  const declaredList = drift.declared || []
  const observedList = drift.observed || []
  const undeclaredList = drift.undeclared || []

  const observedFieldNames = observedList.map((o) => o.field)
  const allUniqueFieldsSet = new Set([...declaredList, ...observedFieldNames])
  const totalUniqueFields = allUniqueFieldsSet.size
  const undeclaredCount = undeclaredList.length
  // One row per field, undeclared first: Field | In the notice? | Where it was seen.
  const driftRows = [...allUniqueFieldsSet]
    .map((field) => ({
      field,
      declared: declaredList.includes(field),
      undeclared: undeclaredList.includes(field),
      where: observedList.find((o) => o.field === field)?.where || []
    }))
    .sort((x, y) => y.undeclared - x.undeclared)

  const fix = selectedFinding?.fix || {}
  const fixMode = selectedFinding ? fixMeta[selectedFinding.id] : null
  const showResult =
    Boolean(selectedFinding) &&
    (selectedFinding.status === 'verified_fixed' || fix.rescan_passed != null || fix.tests_passed != null)

  const views = [
    { key: 'findings', label: 'Findings', count: sortedFindings.length, countText: 'findings' },
    { key: 'notice_drift', label: 'Notice vs Runtime', count: undeclaredCount, countText: 'undeclared fields', alert: undeclaredCount > 0 },
    { key: 'data_flow', label: 'Data Flow' }
  ]
  const showResults = hasScan && !isScanning
  const fixable = (scanData.findings || []).filter((f) => f.fix?.available)
  const allFixed = !sampleMode && fixable.length > 0 && fixable.every((f) => f.status === 'verified_fixed')
  const cachedCount = fixable.filter((f) => fixMeta[f.id]?.mode === 'cached_golden').length
  const manualCount = (scanData.findings || []).length - fixable.length
  const firstRun = !hasScan && !isScanning && activeTab === 'findings'
  const pageTitle = firstRun ? 'Readiness scan' : views.find((v) => v.key === activeTab)?.label

  return (
    <div className="min-h-screen bg-paper text-ink font-sans">
      {/* 1. Left rail: brand, views, then target and engine status. A top block below the lg breakpoint. */}
      <aside className="bg-surface border-b border-line lg:border-b-0 lg:border-r lg:fixed lg:inset-y-0 lg:left-0 lg:w-[220px] flex flex-col print:hidden">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
          <LogoMark className="w-7 h-7 text-accent shrink-0" />
          <span className="font-serif text-[22px] font-semibold leading-none text-ink">DPDP Lens</span>
        </div>

        <nav aria-label="Views" className="flex lg:flex-col gap-1 px-3 pb-3">
          {views.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => setActiveTab(v.key)}
              aria-current={activeTab === v.key ? 'page' : undefined}
              className={`flex items-center gap-2 w-full text-left px-3 py-2.5 rounded-[6px] text-[15px] transition-colors duration-150 cursor-pointer ${
                activeTab === v.key ? 'bg-accent-soft text-ink font-semibold' : 'text-muted hover:bg-paper hover:text-ink font-medium'
              }`}
            >
              {v.label}
              {(hasScan || sampleMode) && v.count != null && (
                <span className={`ml-auto font-mono text-[14px] tabular ${v.alert ? 'text-critical font-semibold' : 'text-muted'}`}>
                  {v.count}
                  <span className="sr-only"> {v.countText}</span>
                </span>
              )}
            </button>
          ))}
        </nav>

        <div className="lg:mt-auto flex flex-col gap-2 px-5 py-4 border-t border-line text-[13px]">
          <div className="flex flex-col">
            <span className="text-muted">Target</span>
            <span className="font-mono text-ink break-all">{scanData.target || SCAN_REQUEST.target_url}</span>
          </div>
          <span className="text-muted tabular">
            {hasScan
              ? `Scanned ${new Date(scanData.scanned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
              : 'No scan yet'}
          </span>
          {/* Engine status. Sample data only after a click on "Use sample data". */}
          <span className={`inline-flex items-center gap-2 ${sampleMode || engineConnected === false ? 'text-high font-medium' : 'text-muted'}`}>
            <span
              aria-hidden="true"
              className={`w-2 h-2 rounded-full shrink-0 ${
                sampleMode || engineConnected === false ? 'bg-high' : engineConnected ? 'bg-accent' : 'bg-muted'
              }`}
            />
            {sampleMode
              ? 'Sample Data Mode'
              : engineConnected
              ? 'Live Engine (:8100)'
              : engineConnected === false
              ? 'Engine offline'
              : 'Checking engine...'}
          </span>
        </div>
      </aside>

      <div className="lg:pl-[220px] min-h-screen flex flex-col">
        <div className="w-full max-w-[1280px] px-8 flex-1 flex flex-col">
          {/* 2. Page header: title on the left, actions on the right */}
          <header className="pt-6 pb-2 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <h1 className="font-serif text-[28px] leading-tight font-semibold text-ink m-0">{pageTitle}</h1>
              {sampleMode && <Tag>SAMPLE</Tag>}
            </div>
            <div className="flex items-center gap-5 print:hidden">
              {sampleMode && scoreHistory && (
                <button
                  type="button"
                  onClick={handleResetDemo}
                  className="text-[15px] text-muted hover:text-ink underline-offset-4 hover:underline transition-colors duration-150 cursor-pointer"
                  title="Reset demo state"
                >
                  Reset demo
                </button>
              )}
              {sampleMode && (
                <button
                  type="button"
                  onClick={handleBackToLive}
                  className="text-[15px] text-muted hover:text-ink underline-offset-4 hover:underline transition-colors duration-150 cursor-pointer"
                >
                  Back to live engine
                </button>
              )}
              {hasScan && (
              <button
                type="button"
                onClick={handleExportReport}
                className="text-[15px] font-medium text-accent hover:text-accent-hover underline-offset-4 hover:underline transition-colors duration-150 cursor-pointer"
              >
                Export report
              </button>
              )}
              {/* The first-run screen has its own Run scan button, so there is only ever one. */}
              {!firstRun && (
              <button
                type="button"
                disabled={isScanning}
                onClick={handleRunScan}
                className="px-5 py-2.5 rounded-[6px] bg-accent hover:bg-accent-hover disabled:opacity-60 text-white text-[15px] font-medium transition-colors duration-150 cursor-pointer"
              >
                {isScanning ? 'Scanning...' : 'Run scan'}
              </button>
              )}
            </div>
          </header>

          {/* Red banner: the engine's own error text. Never replaced by sample data. */}
          {scanError && (
            <div role="alert" className="mt-4 bg-surface border border-line border-l-4 border-l-critical rounded-[6px] px-4 py-2.5 text-[15px] text-critical print:hidden">
              <strong>Scan failed:</strong> {scanError}
            </div>
          )}

          {fixError && (
            <div role="alert" className="mt-4 bg-surface border border-line border-l-4 border-l-critical rounded-[6px] px-4 py-2.5 text-[15px] text-critical print:hidden">
              <strong>Fix failed:</strong> {fixError}. The finding stays open.
            </div>
          )}

          {/* Engine unreachable. Sample data only on a click. */}
          {engineConnected === false && !sampleMode && (
            <div className="mt-4 bg-surface border border-line border-l-4 border-l-high rounded-[6px] px-4 py-2.5 text-[15px] text-high flex flex-wrap items-center gap-4 print:hidden">
              <span>Engine not reachable at {API_BASE}.</span>
              <button
                type="button"
                onClick={handleUseSample}
                className="font-medium text-accent hover:text-accent-hover underline underline-offset-4 cursor-pointer"
              >
                Use sample data
              </button>
            </div>
          )}

      {/* Main Content Area */}
      <main className="py-6 flex-1 flex flex-col gap-6">
        {/* Scanning: the five layers tick from the engine's real progress. Skeleton rows, no spinner. */}
        {isScanning && (
          <>
            <section aria-live="polite" aria-label="Scan progress" className="bg-surface border border-line rounded-[6px] p-5 flex flex-col gap-4 print:hidden">
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-serif text-[20px] font-semibold text-ink">
                  Scanning {sampleMode ? 'sample data' : SCAN_REQUEST.target_url}
                </span>
                <span className="font-mono text-[14px] text-muted tabular">
                  {scanProgress
                    ? scanProgress.done >= scanProgress.total
                      ? `${scanProgress.total} of ${scanProgress.total} steps done`
                      : `Step ${scanProgress.done + 1} of ${scanProgress.total}`
                    : ''}
                  {scanStartedAt !== null && !sampleMode && (
                    <>
                      {' · '}
                      <Elapsed since={scanStartedAt} />
                    </>
                  )}
                </span>
              </div>
              <ol className="list-none p-0 m-0 grid grid-cols-2 sm:grid-cols-5 gap-3">
                {SCAN_LAYERS.map(([name, steps]) => {
                  const state = layerState(steps, scanProgress)
                  const ms = state === 'done' ? layerMs(steps, scanProgress) : null
                  return (
                    <li key={name} className={`flex items-center gap-2 text-[15px] ${state === 'pending' ? 'text-muted' : 'text-ink font-medium'}`}>
                      <StepMarker state={state} />
                      {name}
                      {ms !== null && <span className="font-mono text-[13px] font-normal text-muted tabular">{secs(ms)}</span>}
                    </li>
                  )
                })}
              </ol>
              <div className="text-[15px] text-ink">
                {scanProgress
                  ? scanProgress.step
                    ? SCAN_STEP_LABELS[scanProgress.step] || scanProgress.step
                    : 'All checks finished'
                  : sampleMode
                  ? 'Loading the sample scan'
                  : 'Starting the scan'}
              </div>
            </section>
            <div aria-hidden="true" className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-pulse">
              <div className="lg:col-span-5 bg-surface border border-line rounded-[6px] overflow-hidden">
                {[0, 1, 2, 3, 4, 5].map((k) => (
                  <div key={k} className="flex items-start gap-3 px-4 py-4 border-b border-line last:border-b-0">
                    <span className="w-16 h-3 rounded bg-line" />
                    <span className="flex-1 flex flex-col gap-2">
                      <span className="h-3 rounded bg-line w-4/5" />
                      <span className="h-3 rounded bg-line w-1/4" />
                    </span>
                  </div>
                ))}
              </div>
              <div className="lg:col-span-7 bg-surface border border-line rounded-[6px] p-6 flex flex-col gap-4">
                <span className="h-5 rounded bg-line w-3/5" />
                <span className="h-3 rounded bg-line w-full" />
                <span className="h-3 rounded bg-line w-5/6" />
                <span className="h-24 rounded bg-line w-full" />
              </div>
            </div>
          </>
        )}

        {/* First run: no scan yet */}
        {firstRun && (
          <section aria-label="First run" className="flex flex-col items-start gap-5 py-12 max-w-[680px]">
            <LogoMark className="w-12 h-12 text-accent" />
            <h2 className="font-serif text-[36px] leading-tight font-semibold text-ink m-0">
              Does your app do what its privacy notice says?
            </h2>
            <p className="text-[16px] leading-relaxed text-muted m-0">
              DPDP Lens checks the database, code, running API and browser of{' '}
              <span className="font-mono text-ink">{SCAN_REQUEST.target_url}</span>, maps each finding to the DPDP Act and Rules,
              and proves a fix on a sandbox copy before calling it verified.
            </p>
            <button
              type="button"
              onClick={handleRunScan}
              className="px-6 py-3 rounded-[6px] bg-accent hover:bg-accent-hover text-white text-[16px] font-medium transition-colors duration-150 cursor-pointer"
            >
              Run scan
            </button>
          </section>
        )}

        {/* 3. Score hero: the big number, then one stacked bar of open findings by severity */}
        {showResults && (
        <section className="flex flex-wrap items-end gap-x-14 gap-y-5 pb-6 border-b border-line" aria-label="Summary">
          <div className="flex items-end gap-4">
            <div className="font-serif text-[72px] leading-[0.85] font-semibold text-ink tabular">{score ?? '-'}</div>
            <div className="flex flex-col pb-0.5">
              <span className="text-[16px] text-muted tabular">/ 100</span>
              <span className="font-serif text-[22px] leading-tight font-semibold text-ink">{readiness(score)}</span>
            </div>
          </div>

          {scoreHistory && (
            <div className="flex flex-col pb-0.5">
              <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">Score change</span>
              <span className="font-serif text-[22px] leading-tight font-semibold text-accent tabular">
                {scoreHistory.before} to {scoreHistory.after}
              </span>
            </div>
          )}

          <div className="flex-1 min-w-[280px] max-w-[520px] flex flex-col gap-2.5 pb-1 ml-auto">
            <div className={`flex gap-0.5 h-3 rounded-[3px] overflow-hidden ${openTotal ? '' : 'bg-line'}`} aria-hidden="true">
              {SEVERITIES.map(
                (sev) =>
                  scanData.counts?.[sev] > 0 && (
                    <div key={sev} className={SEVERITY_STYLES[sev].bar} style={{ flex: `${scanData.counts[sev]} 1 0` }} />
                  )
              )}
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              {SEVERITIES.map((sev) => (
                <span key={sev} className="inline-flex items-center gap-2 text-[15px]">
                  <span aria-hidden="true" className={`w-2.5 h-2.5 rounded-[2px] ${SEVERITY_STYLES[sev].bar}`} />
                  <span className={`font-medium ${SEVERITY_STYLES[sev].text}`}>{SEVERITY_STYLES[sev].label}</span>{' '}
                  <span className="font-mono font-medium text-ink tabular">{scanData.counts?.[sev] ?? '-'}</span>
                </span>
              ))}
            </div>
          </div>
        </section>
        )}

        {/* All findings that have a fix template are verified (live only, sample fixes are simulated) */}
        {activeTab === 'findings' && showResults && allFixed && (
          <section
            aria-label="All fixes verified"
            className="bg-accent-soft border border-line rounded-[6px] px-5 py-4 flex flex-wrap items-center justify-between gap-4"
          >
            <div className="flex flex-col gap-1">
              <span className="font-serif text-[20px] font-semibold text-ink">
                All {fixable.length} findings with a fix template are verified
              </span>
              <span className="text-[15px] text-muted tabular">
                {scoreHistory && `Score ${scoreHistory.before} to ${scoreHistory.after}. `}
                {manualCount} {manualCount === 1 ? 'finding still needs' : 'findings still need'} a manual change.
                {cachedCount > 0 && ` ${cachedCount} of the results came from cached runs.`}
              </span>
            </div>
            <button
              type="button"
              onClick={handleExportReport}
              className="px-4 py-2 rounded-[6px] border border-line bg-surface hover:bg-paper text-ink text-[15px] font-medium transition-colors duration-150 cursor-pointer"
            >
              Export the report
            </button>
          </section>
        )}

        {/* 4. Tab 1: Findings Split View */}
        {activeTab === 'findings' && showResults && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column: Findings List, grouped by severity */}
            <section
              className="lg:col-span-5 bg-surface border border-line rounded-[6px] overflow-hidden"
              aria-label="Findings list"
            >
              <div className="px-4 py-3 border-b border-line flex items-baseline justify-between">
                <h2 className="font-serif text-[20px] font-semibold text-ink m-0">Findings ({sortedFindings.length})</h2>
                <span className="text-[13px] text-muted">↑ ↓ to move</span>
              </div>

              {sortedFindings.length === 0 && (
                <div className="p-6 text-[15px] text-muted">
                  {hasScan
                    ? 'No findings from the checks we ran. The checks are limited, so this is not a compliance result.'
                    : 'No scan yet. Click Run scan.'}
                </div>
              )}

              {SEVERITIES.map((sev) => {
                const group = sortedFindings.filter((f) => f.severity === sev)
                if (!group.length) return null
                return (
                  <div key={sev}>
                    <div className="px-4 py-1.5 bg-paper border-b border-line text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
                      {SEVERITY_STYLES[sev].label} ({group.length})
                    </div>
                    {group.map((finding) => {
                      const isSelected = selectedFinding?.id === finding.id
                      const style = SEVERITY_STYLES[sev]
                      const isFixed = finding.status === 'verified_fixed'

                      return (
                        <div
                          key={finding.id}
                          id={`finding-row-${finding.id}`}
                          onClick={() => setSelectedFindingId(finding.id)}
                          tabIndex={0}
                          role="button"
                          aria-pressed={isSelected}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              setSelectedFindingId(finding.id)
                            }
                          }}
                          className={`flex items-start gap-3 pl-3 pr-4 py-3 border-b border-line border-l-[3px] cursor-pointer transition-colors duration-150 ${
                            isSelected ? 'bg-accent-soft border-l-accent' : 'border-l-transparent hover:bg-paper'
                          }`}
                        >
                          <span className="flex items-center gap-2 w-[76px] shrink-0 pt-0.5">
                            <span aria-hidden="true" className={`w-1 h-4 rounded-[1px] ${style.bar}`} />
                            <span className={`text-[13px] font-semibold ${style.text}`}>{style.label}</span>
                          </span>
                          <span className="flex-1 min-w-0 flex flex-col gap-0.5">
                            <span className="text-[15px] font-medium text-ink leading-snug">{finding.title}</span>
                            <span className="text-[13px] text-muted">{LAYER_NAMES[finding.layer] || finding.layer}</span>
                          </span>
                          <span className={`text-[13px] shrink-0 pt-0.5 ${isFixed ? 'text-accent font-semibold' : 'text-muted'}`}>
                            {isFixed ? 'Verified fixed' : 'Open'}
                            {isFixed && fixMeta[finding.id]?.mode === 'cached_golden' && ' · cached'}
                            {isFixed && sampleMode && ' · simulated'}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )
              })}
            </section>

            {/* Right Column: Finding Detail Panel */}
            <section
              className="lg:col-span-7 bg-surface border border-line rounded-[6px] p-6 flex flex-col gap-6 lg:sticky lg:top-6 lg:max-h-[calc(100vh-48px)] overflow-y-auto"
              aria-label="Finding detail"
            >
              {selectedFinding ? (
                <>
                  {/* 1. Title */}
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] text-muted">
                      <span className="font-mono">{selectedFinding.id}</span>
                      <span aria-hidden="true">·</span>
                      <span>{LAYER_NAMES[selectedFinding.layer] || selectedFinding.layer}</span>
                      {selectedFinding.status === 'verified_fixed' && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-accent font-semibold">Verified fixed</span>
                        </>
                      )}
                      <span
                        className={`ml-auto inline-flex items-center gap-2 font-semibold ${
                          (SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).text
                        }`}
                      >
                        <span
                          aria-hidden="true"
                          className={`w-1 h-4 rounded-[1px] ${(SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).bar}`}
                        />
                        {(SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).label}
                      </span>
                    </div>
                    <h2 className="font-serif text-[26px] leading-tight font-semibold text-ink m-0">{selectedFinding.title}</h2>
                  </div>

                  {/* 2. Plain English Explanation */}
                  <p className="text-[16px] leading-relaxed text-ink m-0">{selectedFinding.explanation}</p>

                  {/* 3. Law, as plain lines */}
                  <div className="flex flex-col gap-2">
                    <Label>Law</Label>
                    <ul className="list-none p-0 m-0 flex flex-col gap-1">
                      {(selectedFinding.clauses || []).map((clause, idx) => (
                        <li key={idx} className="text-[15px] text-ink">
                          <span className="font-mono font-medium">{clause.ref}</span>, {clause.note}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 4. Evidence, set like a workpaper exhibit */}
                  <div className="flex flex-col gap-2">
                    <Label>Evidence</Label>
                    <div className="border border-line rounded-[6px] overflow-hidden">
                      <div className="flex items-center justify-between gap-3 px-3 py-2 bg-paper border-b border-line text-[13px] text-muted">
                        <span className="font-mono break-all">
                          {formatLocation(selectedFinding.evidence?.location) || 'No location recorded'}
                        </span>
                        <span className="uppercase tracking-[0.06em] shrink-0">{selectedFinding.evidence?.kind || 'observed'}</span>
                      </div>
                      <div className="px-3 py-3 flex flex-col gap-2">
                        <p className="text-[15px] text-ink m-0">{selectedFinding.evidence?.summary}</p>
                        {selectedFinding.evidence?.masked_sample && (
                          <div className="flex flex-col gap-1">
                            <span className="text-[13px] text-muted">Masked sample</span>
                            <code className="block font-mono text-[14px] text-ink bg-paper rounded-[4px] px-3 py-2 break-all">
                              {selectedFinding.evidence.masked_sample}
                            </code>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 5. Fix and verify */}
                  <div className="pt-6 border-t border-line flex flex-col gap-4">
                    {fixingFindingId === selectedFinding.id && (
                      <div aria-live="polite" className="flex flex-col gap-3">
                        <div className="flex items-baseline justify-between">
                          <Label>Fix and verify on a sandbox copy</Label>
                          <span className="font-mono text-[13px] text-muted tabular">
                            {currentStepIndex < 0 ? (
                              <>
                                Running · <Elapsed since={fixStartedAt} />
                              </>
                            ) : (
                              `Engine took ${secs(fixLog.total_ms)}`
                            )}
                          </span>
                        </div>
                        {currentStepIndex < 0 && (
                          <p className="text-[14px] text-muted m-0">
                            The engine measures each step and reports them when the run ends.
                          </p>
                        )}
                        <ol className="list-none p-0 m-0 flex flex-col gap-2.5">
                          {FIX_STEPS.map(([key, stepText], sIdx) => {
                            const isDone = sIdx < currentStepIndex
                            const isCurrent = sIdx === currentStepIndex
                            const ms = isDone ? fixLog?.steps.find((x) => x.step === key)?.ms : null
                            return (
                              <li key={key} className="flex items-center gap-3 text-[15px]">
                                <StepMarker state={isDone ? 'done' : isCurrent ? 'current' : 'pending'} />
                                <span className={isDone ? 'text-ink' : isCurrent ? 'text-ink font-medium' : 'text-muted'}>{stepText}</span>
                                {ms != null && <span className="ml-auto font-mono text-[13px] text-muted tabular">{secs(ms)}</span>}
                              </li>
                            )
                          })}
                        </ol>
                      </div>
                    )}

                    {showResult && (
                      <div className="flex flex-col gap-4">
                        {/* Result mark. Sample mode never claims VERIFIED; a failed fix says so in red. */}
                        <div className="flex flex-wrap items-center justify-between gap-4">
                          {sampleMode ? (
                            <span className="font-mono text-[15px] font-semibold tracking-[0.12em] px-3 py-1 border-2 border-high text-high rounded-[4px]">
                              SIMULATED
                            </span>
                          ) : fix.verified ? (
                            <span className="inline-flex items-center gap-2 font-mono text-[15px] font-semibold tracking-[0.12em] px-3 py-1 border-2 border-accent text-accent rounded-[4px]">
                              <svg aria-hidden="true" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                              </svg>
                              VERIFIED
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-2 font-mono text-[15px] font-semibold tracking-[0.12em] px-3 py-1 border-2 border-critical text-critical rounded-[4px]">
                              <svg aria-hidden="true" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                              NOT VERIFIED
                            </span>
                          )}
                          {fix.verified && fix.score_before != null && fix.score_after != null && (
                            <span className="flex items-baseline gap-2">
                              <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">Score</span>
                              <span className="font-serif text-[22px] font-semibold text-ink tabular">
                                {fix.score_before} to {fix.score_after}
                              </span>
                            </span>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pb-4 border-b border-line">
                          <StatusBadge label="Re-scan passed" passed={fix.rescan_passed} />
                          <StatusBadge label="Tests passed" passed={fix.tests_passed} />
                          <StatusBadge label="Verified" passed={fix.verified} />
                        </div>

                        {sampleMode ? (
                          <span className="self-start text-[13px] font-semibold px-2 py-0.5 rounded-[4px] border border-high text-high">
                            Simulated (sample data)
                          </span>
                        ) : fixMode?.mode === 'cached_golden' ? (
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] px-3 py-2 rounded-[6px] border border-high text-high">
                            <Tag>CACHED</Tag>
                            <span className="font-semibold">Cached golden patch mode</span>
                            <span>
                              {fixMode.fallbackReason
                                ? `Live run could not finish: ${fixMode.fallbackReason}`
                                : 'Replayed from a saved verified run, not run just now.'}
                            </span>
                          </div>
                        ) : null}

                        {fix.verified ? (
                          <p className="flex items-center gap-2 text-accent text-[16px] font-medium m-0">
                            <svg aria-hidden="true" className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                            <span>
                              {sampleMode
                                ? 'Simulated. No real re-scan or tests were run.'
                                : fixMode?.mode === 'cached_golden'
                                ? 'Verified in a saved run. It was not run just now.'
                                : "Verified. Re-scan passed and the app's tests still pass."}
                            </span>
                          </p>
                        ) : (
                          <div className="text-critical text-[16px] font-medium border-l-4 border-critical pl-3 py-1">
                            Not verified.
                            {fix.rescan_passed === false && ' The problem is still found after the fix.'}
                            {fix.tests_passed === false && " The app's tests failed."} The finding stays open.
                          </div>
                        )}

                        {fix.diff && (
                          <div className="flex flex-col gap-2">
                            <Label>Patch (unified diff)</Label>
                            <DiffViewer diffText={fix.diff} />
                          </div>
                        )}

                        {/* Verification log: only from the live run's own measurements. Cached and sample results have none. */}
                        {!sampleMode && fixMode?.verification && (
                          <div className="flex flex-col gap-2">
                            <Label>Verification log</Label>
                            <div className="border border-line rounded-[6px] overflow-hidden text-[14px]">
                              <ol className="list-none p-0 m-0">
                                {FIX_STEPS.map(([key, stepText]) => {
                                  const ms = fixMode.verification.steps.find((x) => x.step === key)?.ms
                                  return (
                                    <li key={key} className="flex items-center gap-3 px-3 py-1.5 border-b border-line">
                                      <StepMarker state={ms != null ? 'done' : 'pending'} />
                                      <span className="text-ink">{stepText}</span>
                                      <span className="ml-auto font-mono text-muted tabular">{ms != null ? secs(ms) : '—'}</span>
                                    </li>
                                  )
                                })}
                              </ol>
                              <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1 px-3 py-3 m-0 bg-paper">
                                <dt className="text-muted">Sandbox</dt>
                                <dd className="m-0 font-mono break-all">
                                  {fixMode.verification.sandbox} <span className="font-sans text-muted">(deleted after the run)</span>
                                </dd>
                                <dt className="text-muted">Patched app</dt>
                                <dd className="m-0 font-mono">127.0.0.1:{fixMode.verification.port}</dd>
                                <dt className="text-muted">Check re-run</dt>
                                <dd className="m-0">
                                  <span className="font-mono">{fixMode.verification.rescan_check}</span>: finding{' '}
                                  <span className={fixMode.verification.rescan_result === 'gone' ? 'text-accent font-medium' : 'text-critical font-medium'}>
                                    {fixMode.verification.rescan_result}
                                  </span>{' '}
                                  ({fixMode.verification.rescan_findings} findings in the re-scan of this copy)
                                </dd>
                                <dt className="text-muted">pytest</dt>
                                <dd className="m-0 font-mono">{fixMode.verification.pytest_summary}</dd>
                                <dt className="text-muted">Total</dt>
                                <dd className="m-0 font-mono tabular">{secs(fixMode.verification.total_ms)}</dd>
                              </dl>
                            </div>
                          </div>
                        )}

                        {!sampleMode && fix.verified && fix.diff && (
                          <div className="flex flex-wrap items-center justify-between gap-3 text-[14px] text-muted">
                            <span>Verified on a sandbox copy. Your original code is unchanged. Download the patch to apply it.</span>
                            <div className="flex items-center gap-2 shrink-0">
                              <button
                                type="button"
                                onClick={() => copyDiff(selectedFinding)}
                                className="px-3 py-1.5 rounded-[6px] border border-line bg-surface hover:bg-paper text-ink text-[14px] font-medium transition-colors duration-150 cursor-pointer"
                              >
                                {copyState?.id === selectedFinding.id ? (copyState.ok ? 'Copied' : 'Copy failed') : 'Copy diff'}
                              </button>
                              <button
                                type="button"
                                onClick={() => downloadPatch(selectedFinding)}
                                className="px-3 py-1.5 rounded-[6px] border border-line bg-surface hover:bg-paper text-ink text-[14px] font-medium transition-colors duration-150 cursor-pointer"
                              >
                                Download patch
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {selectedFinding.status !== 'verified_fixed' && (
                      <div className="flex flex-wrap items-center justify-between w-full gap-4">
                        <div className="flex flex-col gap-1 max-w-[400px]">
                          <span className="text-[16px] text-ink font-semibold">
                            {fix.available
                              ? sampleMode
                                ? 'Simulated fix (sample data)'
                                : 'Verified fix available'
                              : 'This finding needs a manual change'}
                          </span>
                          <span className="text-[14px] text-muted">
                            {fix.available
                              ? sampleMode
                                ? 'No real sandbox run happens in sample mode'
                                : "Proposed on a sandbox copy. Counts as verified only if the re-scan and the app's tests pass."
                              : 'No patch template exists for it yet'}
                          </span>
                        </div>
                        {fix.available ? (
                          <div className="flex items-center gap-5 shrink-0">
                            {!sampleMode && (
                              <button
                                type="button"
                                disabled={fixingFindingId !== null}
                                onClick={() => handleFixAndVerify(selectedFinding, 'cached')}
                                title="Show the saved result of an earlier verified run. Labelled as cached."
                                className="text-[15px] text-accent hover:text-accent-hover underline underline-offset-4 disabled:opacity-50 transition-colors duration-150 cursor-pointer"
                              >
                                Use cached result
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={fixingFindingId !== null}
                              onClick={() => handleFixAndVerify(selectedFinding)}
                              className="px-5 py-2.5 rounded-[6px] bg-accent hover:bg-accent-hover disabled:opacity-50 text-white font-medium text-[16px] transition-colors duration-150 cursor-pointer"
                            >
                              Fix and verify
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            disabled
                            className="px-5 py-2.5 rounded-[6px] border border-line bg-paper text-muted font-medium text-[16px] cursor-not-allowed shrink-0"
                          >
                            No fix template yet
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="text-center py-12 text-[15px] text-muted">
                  {hasScan ? 'Select a finding to see its evidence and the law it maps to.' : 'Run a scan to see findings here.'}
                </div>
              )}
            </section>
          </div>
        )}

        {/* 5. Tab 2: Notice vs Runtime */}
        {activeTab === 'notice_drift' && !isScanning && !scanData.notice_drift && (
          <section
            className="bg-surface border border-line rounded-[6px] p-8 text-center flex flex-col gap-2"
            aria-label="Notice vs Runtime Truth"
          >
            <h2 className="font-serif text-[22px] font-semibold text-ink m-0">No drift data yet</h2>
            <p className="text-[15px] text-muted m-0">
              {hasScan
                ? 'The engine returned no Notice vs Runtime data for this scan.'
                : 'Run a scan to compare the privacy notice with what the app handles.'}
            </p>
          </section>
        )}

        {activeTab === 'notice_drift' && !isScanning && scanData.notice_drift && (
          <section className="flex flex-col gap-5" aria-label="Notice vs Runtime Truth">
            <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-2">
              <div className="flex flex-col gap-1.5 max-w-[860px]">
                <h2 className={`font-serif text-[28px] leading-tight font-semibold m-0 ${undeclaredCount ? 'text-critical' : 'text-ink'}`}>
                  {undeclaredCount} of {totalUniqueFields} data fields the app handles are not in its privacy notice
                </h2>
                <p className="text-[15px] text-muted m-0">
                  Notice duties: Act s5, Rule 3 (a standalone, plain language notice that itemises the personal data and its purposes).
                </p>
              </div>
              <span className="text-[14px] text-muted">
                Notice read from <span className="font-mono text-ink">/notice</span>
              </span>
            </div>

            <div className="bg-surface border border-line rounded-[6px] overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="bg-paper border-b border-line text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
                    <th scope="col" className="pl-5 pr-4 py-2.5 font-semibold w-[200px]">Field</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold w-[220px]">In the notice?</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold">Where it was seen</th>
                  </tr>
                </thead>
                <tbody>
                  {driftRows.map((row) => (
                    <tr key={row.field} className={`border-b border-line last:border-b-0 ${row.undeclared ? 'bg-[#FBF3F1]' : ''}`}>
                      <th
                        scope="row"
                        className={`pl-4 pr-4 py-3 border-l-4 font-mono text-[16px] font-medium text-left ${
                          row.undeclared ? 'border-l-critical text-critical' : 'border-l-transparent text-ink'
                        }`}
                      >
                        {row.field}
                      </th>
                      <td className="px-4 py-3 text-[15px]">
                        {row.undeclared ? (
                          <span className="font-semibold text-critical">Not in the notice</span>
                        ) : row.declared ? (
                          <span className="text-ink">Yes</span>
                        ) : (
                          <span className="text-muted">No</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {row.where.length ? (
                          <span className="flex flex-wrap gap-1.5">
                            {row.where.map((loc) => (
                              <span key={loc} className="font-mono text-[14px] text-ink bg-paper border border-line rounded-[4px] px-2 py-0.5">
                                {loc}
                              </span>
                            ))}
                          </span>
                        ) : (
                          <span className="text-[15px] text-muted">Not observed in this scan</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-[14px] text-muted m-0">
              Where it was seen: <span className="font-mono">db:</span> a database column, <span className="font-mono">api:</span> an API
              response without login, <span className="font-mono">request:</span> a request to a third party. The Data Flow view shows
              the same data by layer.
            </p>
          </section>
        )}

        {/* 6. Data Flow: where each field was seen, by layer. Built only from notice_drift. */}
        {activeTab === 'data_flow' && !isScanning && !scanData.notice_drift && (
          <section
            className="bg-surface border border-line rounded-[6px] p-8 text-center flex flex-col gap-2"
            aria-label="Data Flow"
          >
            <h2 className="font-serif text-[22px] font-semibold text-ink m-0">No data flow yet</h2>
            <p className="text-[15px] text-muted m-0">
              {hasScan
                ? 'The engine returned no Notice vs Runtime data for this scan, so there is nothing to map.'
                : 'Run a scan to see where each personal data field appears: notice, database, API and browser.'}
            </p>
          </section>
        )}

        {activeTab === 'data_flow' && !isScanning && scanData.notice_drift && (
          <section className="flex flex-col gap-4" aria-label="Data Flow">
            <p className="text-[16px] text-ink m-0">
              Where each of the {totalUniqueFields} personal data fields was seen.{' '}
              {undeclaredCount > 0 && (
                <span className="text-critical font-semibold">
                  {undeclaredCount} {undeclaredCount === 1 ? 'is' : 'are'} not in the notice.
                </span>
              )}
            </p>

            {/* Field lanes: one per field, nodes only where the engine saw the field, lines join consecutive nodes. */}
            <div className="bg-surface border border-line rounded-[6px] overflow-x-auto">
              <div className="min-w-[820px]">
                <div data-testid="lane-head" className="grid grid-cols-[170px_1fr] bg-paper border-b border-line text-[14px] font-semibold text-muted">
                  <div className="pl-5 pr-4 py-3">Field</div>
                  <div className="grid grid-cols-4">
                    {LANE_COLS.map(([key, name]) => (
                      <div key={key} className="px-4 py-3">{name}</div>
                    ))}
                  </div>
                </div>
                <ul aria-label="Fields by layer" className="list-none m-0 p-0">
                  {driftRows.map((row) => {
                    const bg = row.undeclared ? 'bg-[#FBF3F1]' : 'bg-surface'
                    const seenIn = (prefix) => row.where.filter((w) => w.startsWith(`${prefix}:`))
                    // Stops: the notice mark, then every layer column where the field was seen. Segments join neighbours.
                    const stops = [0, ...LANE_COLS.slice(1).flatMap(([prefix], k) => (seenIn(prefix).length ? [k + 1] : []))]
                    const lineClass = row.undeclared ? 'h-1 bg-critical' : 'h-0.5 bg-accent'
                    return (
                      <li key={row.field} data-field={row.field} className={`grid grid-cols-[170px_1fr] border-b border-line last:border-b-0 ${bg}`}>
                        <div
                          className={`pl-4 pr-4 py-4 border-l-4 font-mono text-[16px] font-medium leading-5 ${
                            row.undeclared ? 'border-l-critical text-critical' : 'border-l-transparent text-ink'
                          }`}
                        >
                          {row.field}
                        </div>
                        <div className="relative grid grid-cols-4">
                          {stops.slice(1).map((b, k) => {
                            const a = stops[k]
                            return (
                              <span
                                key={b}
                                aria-hidden="true"
                                className={`absolute rounded-full -translate-y-1/2 ${lineClass}`}
                                style={{ top: 26, left: `calc(${a * 25}% + 26px)`, width: `${(b - a) * 25}%` }}
                              />
                            )
                          })}
                          {LANE_COLS.map(([prefix, name], col) => {
                            if (col === 0)
                              return (
                                <div key={prefix} data-col="notice" className="relative px-4 py-4 flex flex-col items-start gap-1.5">
                                  {row.undeclared ? (
                                    <span aria-hidden="true" className={`w-5 h-5 rounded-full border-2 border-critical grid place-items-center ${bg}`}>
                                      <svg className="w-3 h-3 text-critical" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeWidth={4} d="M6 18L18 6M6 6l12 12" />
                                      </svg>
                                    </span>
                                  ) : (
                                    <span className={`rounded-full ${bg}`}>
                                      <StepMarker state={row.declared ? 'done' : 'pending'} />
                                    </span>
                                  )}
                                  <span className={`text-[14px] ${row.undeclared ? 'font-semibold text-critical' : 'text-ink'}`}>
                                    {row.undeclared ? 'Not in the notice' : row.declared ? 'In the notice' : 'Not listed'}
                                  </span>
                                </div>
                              )
                            const seen = seenIn(prefix)
                            return (
                              <div key={prefix} data-col={prefix} className="relative px-4 py-4 flex flex-col items-start gap-1.5">
                                {seen.length ? (
                                  <>
                                    <span aria-hidden="true" className={`w-5 h-5 grid place-items-center rounded-full ${bg}`}>
                                      <span className={`rounded-full ${row.undeclared ? 'w-3.5 h-3.5 bg-critical' : 'w-3 h-3 bg-accent'}`} />
                                    </span>
                                    {seen.map((w) => (
                                      <span key={w} title={w} className="font-mono text-[14px] text-ink break-all cursor-help">
                                        {w.slice(prefix.length + 1)}
                                        <span className="sr-only"> ({w})</span>
                                      </span>
                                    ))}
                                  </>
                                ) : (
                                  <span className={`h-5 px-1 leading-5 text-[15px] text-muted ${bg}`}>
                                    <span aria-hidden="true">—</span>
                                    <span className="sr-only">Not seen in {name}</span>
                                  </span>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>
            </div>

            <p className="text-[14px] text-muted m-0">
              Notice: the field is listed in the privacy notice at <span className="font-mono">/notice</span>. Database: a column
              holding the field. API: a response returned without login. Browser: a request from the signup page to a third party
              that carried the field. A dash means the scan did not see the field there.
              {!driftRows.some((r) => r.where.some((w) => w.startsWith('request:'))) &&
                ' No third-party request was seen as a drift field in this scan, so the Browser column is empty. Trackers are reported as findings (see "Tracking script loads before any consent").'}
            </p>
          </section>
        )}

      </main>

          {/* 4. Footer */}
          <footer className="border-t border-line py-4 text-[14px] text-muted">
            DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027.
          </footer>
        </div>
      </div>
    </div>
  )
}
