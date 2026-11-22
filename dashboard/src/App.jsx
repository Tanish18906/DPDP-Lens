import React, { useState, useEffect, useRef } from 'react'
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

const SEVERITY_STYLES = {
  critical: {
    dot: 'bg-[#FF5C5C]',
    text: 'text-[#FF5C5C]',
    border: 'border-[#FF5C5C]/30',
    bg: 'bg-[#FF5C5C]/10',
    badge: 'border-[#FF5C5C] text-[#FF5C5C] bg-[#FF5C5C]/10'
  },
  high: {
    dot: 'bg-[#FF9F43]',
    text: 'text-[#FF9F43]',
    border: 'border-[#FF9F43]/30',
    bg: 'bg-[#FF9F43]/10',
    badge: 'border-[#FF9F43] text-[#FF9F43] bg-[#FF9F43]/10'
  },
  medium: {
    dot: 'bg-[#F5C451]',
    text: 'text-[#F5C451]',
    border: 'border-[#F5C451]/30',
    bg: 'bg-[#F5C451]/10',
    badge: 'border-[#F5C451] text-[#F5C451] bg-[#F5C451]/10'
  },
  low: {
    dot: 'bg-[#6FA8DC]',
    text: 'text-[#6FA8DC]',
    border: 'border-[#6FA8DC]/30',
    bg: 'bg-[#6FA8DC]/10',
    badge: 'border-[#6FA8DC] text-[#6FA8DC] bg-[#6FA8DC]/10'
  }
}

const FIX_STEPS = [
  'Copy app to a sandbox',
  'Apply patch',
  'Restart patched app',
  'Re-run the failed check',
  "Run the app's tests"
]

const SCAN_STEPS = [
  'Inspecting SQLite database schema and tables',
  'Testing API authentication and IDOR boundaries',
  'Scanning backend source code for plaintext logging',
  'Auditing browser third-party trackers & pixels',
  'Computing Notice vs Runtime data drift'
]

const SEVERITIES = ['critical', 'high', 'medium', 'low']

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
async function runEngineScan() {
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

  for (let attempt = 0; attempt < 25; attempt++) {
    await new Promise((r) => setTimeout(r, 600))
    const res = await fetch(`${API_BASE}/scan/${scan_id}`)
    if (!res.ok) throw await engineError(res)
    const result = await res.json()
    if (result.status !== 'running') return result
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
async function requestFix(scanId, findingId) {
  let res
  try {
    res = await fetch(
      `${API_BASE}/findings/${encodeURIComponent(findingId)}/fix?scan_id=${encodeURIComponent(scanId)}&mode=live`,
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
    <div className="bg-[#0B0F14] border border-[#263140] rounded-[8px] overflow-x-auto text-[13px] font-mono p-3 leading-snug">
      {lines.map((line, idx) => {
        let lineStyle = 'text-[#E6EDF3]'
        let lineBg = 'transparent'

        if (line.startsWith('---') || line.startsWith('+++')) {
          lineStyle = 'text-[#8B98A8] font-bold'
        } else if (line.startsWith('@@')) {
          lineStyle = 'text-[#7AA2F7]'
          lineBg = 'bg-[#7AA2F7]/10'
        } else if (line.startsWith('+')) {
          lineStyle = 'text-[#3DDC97]'
          lineBg = 'bg-[#3DDC97]/15'
        } else if (line.startsWith('-')) {
          lineStyle = 'text-[#FF5C5C]'
          lineBg = 'bg-[#FF5C5C]/15'
        }

        return (
          <div key={idx} className={`px-2 rounded-[2px] whitespace-pre-wrap break-words ${lineStyle} ${lineBg}`}>
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
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[5px] text-[12px] font-medium border ${
        isPassed
          ? 'bg-[#3DDC97]/15 text-[#3DDC97] border-[#3DDC97]/40'
          : isFailed
          ? 'bg-[#FF5C5C]/15 text-[#FF5C5C] border-[#FF5C5C]/40'
          : 'bg-[#19212C] text-[#8B98A8] border-[#263140]'
      }`}
    >
      {isPassed ? (
        <svg className="w-3.5 h-3.5 text-[#3DDC97]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
        </svg>
      ) : isFailed ? (
        <svg className="w-3.5 h-3.5 text-[#FF5C5C]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
        </svg>
      ) : (
        <span className="w-2 h-2 rounded-full bg-[#8B98A8]" />
      )}
      {label}
    </span>
  )
}

export default function App() {
  const [scanData, setScanData] = useState(EMPTY_SCAN)
  const [activeTab, setActiveTab] = useState('findings')
  const [activeTooltipClause, setActiveTooltipClause] = useState(null)

  // Real Engine & Mock Mode States
  const [sampleMode, setSampleMode] = useState(false) // only a click on "Use sample data" turns this on
  const [engineConnected, setEngineConnected] = useState(null) // null = checking, true, false
  const [scanError, setScanError] = useState(null)
  const [isScanning, setIsScanning] = useState(false)
  const [scanStepIndex, setScanStepIndex] = useState(0)

  // Fix workflow states
  const [fixingFindingId, setFixingFindingId] = useState(null)
  const [currentStepIndex, setCurrentStepIndex] = useState(-1)
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

  // Run scan: real engine by default. Any error is shown in a red banner, never replaced by sample data.
  const handleRunScan = async () => {
    setIsScanning(true)
    setScanStepIndex(0)
    setScanError(null)
    setFixError(null)
    setFixMeta({})

    const stepInterval = setInterval(() => {
      setScanStepIndex((prev) => (prev < SCAN_STEPS.length - 1 ? prev + 1 : prev))
    }, 600)

    try {
      if (sampleMode) {
        await new Promise((r) => setTimeout(r, 1800))
        handleUseSample()
      } else {
        const result = await runEngineScan()
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
      clearInterval(stepInterval)
      setIsScanning(false)
    }
  }

  function animateScore(from, to) {
    const startTime = performance.now()
    function animate(now) {
      const progress = Math.min(1, (now - startTime) / 400)
      setAnimatedScore(Math.round(from + (to - from) * progress))
      if (progress < 1) requestAnimationFrame(animate)
    }
    requestAnimationFrame(animate)
  }

  // Fix and verify: sample mode simulates it, live mode asks the engine.
  const handleFixAndVerify = (finding) => {
    if (!finding || fixingFindingId !== null) return
    setFixError(null)
    if (sampleMode) runSimulatedFix(finding)
    else runEngineFix(finding)
  }

  const runSimulatedFix = (finding) => {
    setFixingFindingId(finding.id)
    setCurrentStepIndex(0)

    let step = 0
    const interval = setInterval(() => {
      step += 1
      if (step < FIX_STEPS.length) {
        setCurrentStepIndex(step)
      } else {
        clearInterval(interval)
        finishFix(finding)
      }
    }, 850)
  }

  // The 5 steps are only a loading display. They wait on the last step until the engine answers.
  const runEngineFix = async (finding) => {
    setFixingFindingId(finding.id)
    setCurrentStepIndex(0)
    const ticker = setInterval(() => setCurrentStepIndex((i) => Math.min(i + 1, FIX_STEPS.length - 1)), 850)
    try {
      const { finding: updated, score_before, score_after, mode, fallback_reason } = await requestFix(
        scanData.scan_id,
        finding.id
      )
      setScanData((prev) => {
        const findings = prev.findings.map((f) => (f.id === updated.id ? updated : f))
        return { ...prev, findings, score: score_after, counts: countOpen(findings) }
      })
      setFixMeta((prev) => ({ ...prev, [updated.id]: { mode, fallbackReason: fallback_reason } }))
      if (updated.status === 'verified_fixed') {
        animateScore(score_before, score_after)
        setScoreHistory((prev) => ({ before: prev?.before ?? score_before, after: score_after }))
      }
    } catch (e) {
      setFixError(e.message) // the finding stays open
    } finally {
      clearInterval(ticker)
      setFixingFindingId(null)
      setCurrentStepIndex(-1)
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
  const scoreColor = score === null ? '#8B98A8' : score < 50 ? '#FF5C5C' : score < 80 ? '#FF9F43' : '#3DDC97'

  // Notice drift computed properties
  const drift = scanData.notice_drift || { declared: [], observed: [], undeclared: [] }
  const declaredList = drift.declared || []
  const observedList = drift.observed || []
  const undeclaredList = drift.undeclared || []

  const observedFieldNames = observedList.map((o) => o.field)
  const allUniqueFieldsSet = new Set([...declaredList, ...observedFieldNames])
  const totalUniqueFields = allUniqueFieldsSet.size
  const undeclaredCount = undeclaredList.length

  const fix = selectedFinding?.fix || {}
  const fixMode = selectedFinding ? fixMeta[selectedFinding.id] : null
  const showResult =
    Boolean(selectedFinding) &&
    (selectedFinding.status === 'verified_fixed' || fix.rescan_passed != null || fix.tests_passed != null)

  return (
    <div className="min-h-screen bg-[#0B0F14] text-[#E6EDF3] flex flex-col font-sans">
      {/* 1. Sticky Top Bar */}
      <header className="sticky top-0 z-50 bg-[#121821] border-b border-[#263140] px-6 py-2 print:hidden">
        <div className="max-w-[1280px] mx-auto flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <h1 className="text-[18px] font-semibold tracking-tight text-[#E6EDF3] m-0">DPDP Lens</h1>
            <span className="mono text-[12px] bg-[#19212C] border border-[#263140] px-2 py-0.5 rounded-[6px] text-[#8B98A8]">
              target: {scanData.target || 'no scan yet'}
            </span>
            {hasScan && (
              <span className="text-[12px] text-[#8B98A8] hidden sm:inline">
                scanned: {new Date(scanData.scanned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
            {/* Mode pill: sample data only after a click on "Use sample data" */}
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                sampleMode || engineConnected === false
                  ? 'bg-[#FF9F43]/15 text-[#FF9F43] border-[#FF9F43]/30'
                  : engineConnected
                  ? 'bg-[#3DDC97]/15 text-[#3DDC97] border-[#3DDC97]/30'
                  : 'bg-[#19212C] text-[#8B98A8] border-[#263140]'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  sampleMode || engineConnected === false ? 'bg-[#FF9F43]' : engineConnected ? 'bg-[#3DDC97]' : 'bg-[#8B98A8]'
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

          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[#8B98A8] border border-[#263140] px-2.5 py-0.5 rounded-[6px] hidden lg:inline">
              Readiness report, not a compliance certificate
            </span>
            {sampleMode && scoreHistory && (
              <button
                type="button"
                onClick={handleResetDemo}
                className="px-3 py-1 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#8B98A8] hover:text-[#E6EDF3] text-[13px] transition cursor-pointer"
                title="Reset demo state"
              >
                Reset demo
              </button>
            )}
            <button
              type="button"
              disabled={isScanning}
              onClick={handleRunScan}
              className="px-3 py-1 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#E6EDF3] text-[13px] font-medium transition cursor-pointer flex items-center gap-2"
            >
              {isScanning && <span className="w-3 h-3 rounded-full border-2 border-[#3DDC97] border-t-transparent animate-spin" />}
              {isScanning ? 'Scanning...' : 'Run scan'}
            </button>
            <button
              type="button"
              onClick={handleExportReport}
              className="px-3 py-1 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#E6EDF3] text-[13px] font-medium transition cursor-pointer"
            >
              Export report
            </button>
          </div>
        </div>
      </header>

      {/* Red banner: the engine's own error text. Never replaced by sample data. */}
      {scanError && (
        <div
          role="alert"
          className="bg-[#FF5C5C]/15 border-b border-[#FF5C5C]/40 px-6 py-2 text-center text-[14px] text-[#FF5C5C] print:hidden"
        >
          <strong>Scan failed:</strong> {scanError}
        </div>
      )}

      {fixError && (
        <div
          role="alert"
          className="bg-[#FF5C5C]/15 border-b border-[#FF5C5C]/40 px-6 py-2 text-center text-[14px] text-[#FF5C5C] print:hidden"
        >
          <strong>Fix failed:</strong> {fixError}. The finding stays open.
        </div>
      )}

      {/* Amber banner: engine unreachable. Sample data only on a click. */}
      {engineConnected === false && !sampleMode && (
        <div className="bg-[#FF9F43]/15 border-b border-[#FF9F43]/30 px-6 py-2 text-center text-[14px] text-[#FF9F43] flex items-center justify-center gap-3 print:hidden">
          <span>Engine not reachable at {API_BASE}.</span>
          <button
            type="button"
            onClick={handleUseSample}
            className="underline font-semibold cursor-pointer text-[#E6EDF3] hover:text-white"
          >
            Use sample data
          </button>
        </div>
      )}

      {/* Scanner Progress Modal / Overlay */}
      {isScanning && (
        <div className="max-w-[1280px] w-full mx-auto px-6 pt-4 print:hidden">
          <div className="bg-[#121821] border border-[#3DDC97]/40 rounded-[10px] p-5 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="w-4 h-4 rounded-full border-2 border-[#3DDC97] border-t-transparent animate-spin" />
                <span className="text-[15px] font-semibold text-[#E6EDF3]">
                  Running Cross-Layer DPDP Compliance Scan...
                </span>
              </div>
              <span className="mono text-[12px] text-[#8B98A8]">
                Step {scanStepIndex + 1} of {SCAN_STEPS.length}
              </span>
            </div>

            <div className="text-[14px] text-[#3DDC97]">
              {SCAN_STEPS[scanStepIndex]}
            </div>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="max-w-[1280px] w-full mx-auto px-6 py-3 flex-1 flex flex-col gap-3">
        {/* 2. Summary Row: score and the four counts in one slim row */}
        <section
          className="bg-[#121821] border border-[#263140] rounded-[10px] px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-2"
          aria-label="Summary"
        >
          <div className="flex items-center gap-3">
            <div className="relative w-12 h-12 shrink-0">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="14" fill="none" stroke="#19212C" strokeWidth="4" />
                <circle
                  cx="18"
                  cy="18"
                  r="14"
                  fill="none"
                  stroke={scoreColor}
                  strokeWidth="4"
                  strokeDasharray={`${((score ?? 0) / 100) * 88} 88`}
                  strokeLinecap="round"
                />
              </svg>
              <span
                className="absolute inset-0 flex items-center justify-center text-[18px] font-bold transition-colors duration-300"
                style={{ color: scoreColor }}
              >
                {score ?? '-'}
              </span>
            </div>
            <div className="flex flex-col leading-tight">
              <span className="text-[11px] uppercase tracking-wider text-[#8B98A8] font-semibold">Readiness score</span>
              <span className="text-[15px] font-semibold text-[#E6EDF3]">
                {score === null ? 'No scan yet' : score < 50 ? 'Needs Attention' : score < 80 ? 'Moderate Posture' : 'Good Posture'}
              </span>
              {scoreHistory && (
                <span className="text-[12px] text-[#3DDC97] font-medium">
                  Score: {scoreHistory.before} → {scoreHistory.after} (+{scoreHistory.after - scoreHistory.before})
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {SEVERITIES.map((sev) => (
              <div
                key={sev}
                className="bg-[#19212C] border border-[#263140] rounded-[6px] px-2.5 py-1 flex items-center gap-2"
              >
                <span className={`w-2 h-2 rounded-full ${SEVERITY_STYLES[sev].dot}`} />
                <span className={`text-[12px] font-semibold uppercase tracking-wide ${SEVERITY_STYLES[sev].text}`}>{sev}</span>
                <span className="text-[18px] font-bold text-[#E6EDF3]">{scanData.counts?.[sev] ?? '-'}</span>
              </div>
            ))}
          </div>

          <span className="text-[12px] text-[#8B98A8] ml-auto hidden md:inline">Readiness score. Higher is better.</span>
        </section>

        {/* 3. Navigation Tabs */}
        <div className="flex border-b border-[#263140] gap-8 print:hidden">
          <button
            type="button"
            onClick={() => setActiveTab('findings')}
            className={`pb-2 text-[15px] font-medium transition cursor-pointer flex items-center gap-2 border-b-2 ${
              activeTab === 'findings'
                ? 'border-[#3DDC97] text-[#3DDC97]'
                : 'border-transparent text-[#8B98A8] hover:text-[#E6EDF3]'
            }`}
          >
            Findings
            <span className="text-[12px] px-2 py-0.5 rounded-full bg-[#19212C] border border-[#263140] text-[#E6EDF3]">
              {sortedFindings.length}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('notice_drift')}
            className={`pb-2 text-[15px] font-medium transition cursor-pointer flex items-center gap-2 border-b-2 ${
              activeTab === 'notice_drift'
                ? 'border-[#3DDC97] text-[#3DDC97]'
                : 'border-transparent text-[#8B98A8] hover:text-[#E6EDF3]'
            }`}
          >
            Notice vs Runtime
            {undeclaredCount > 0 && (
              <span className="text-[12px] px-2 py-0.5 rounded-full bg-[#FF5C5C]/20 border border-[#FF5C5C]/40 text-[#FF5C5C] font-semibold">
                {undeclaredCount} drift
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('data_flow')}
            className={`pb-2 text-[15px] font-medium transition cursor-pointer flex items-center gap-2 border-b-2 ${
              activeTab === 'data_flow'
                ? 'border-[#3DDC97] text-[#3DDC97]'
                : 'border-transparent text-[#8B98A8] hover:text-[#E6EDF3]'
            }`}
          >
            Data Flow
          </button>
        </div>

        {/* 4. Tab 1: Findings Split View */}
        {activeTab === 'findings' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
            {/* Left Column: Findings List (40% width on desktop) */}
            <section
              className="lg:col-span-5 bg-[#121821] border border-[#263140] rounded-[10px] overflow-hidden"
              aria-label="Findings list"
            >
              <div className="px-4 py-2 border-b border-[#263140] flex items-center justify-between">
                <span className="text-[14px] font-semibold text-[#E6EDF3]">
                  Findings ({sortedFindings.length})
                </span>
                <span className="text-[12px] text-[#8B98A8]">
                  Use ↑ ↓ to navigate
                </span>
              </div>

              <div className="divide-y divide-[#263140]">
                {sortedFindings.length === 0 && (
                  <div className="p-6 text-[14px] text-[#8B98A8]">
                    {hasScan
                      ? 'No findings from the checks we ran. The checks are limited, so this is not a compliance result.'
                      : 'No scan yet. Click Run scan.'}
                  </div>
                )}
                {sortedFindings.map((finding) => {
                  const isSelected = selectedFinding?.id === finding.id
                  const severity = finding.severity || 'low'
                  const style = SEVERITY_STYLES[severity] || SEVERITY_STYLES.low
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
                      className={`px-3 py-2 transition cursor-pointer flex flex-col gap-1 border-l-4 ${
                        isSelected
                          ? 'bg-[#19212C] border-l-[#3DDC97]'
                          : 'border-l-transparent hover:bg-[#19212C]/60'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[5px] text-[11px] font-semibold uppercase tracking-wider border ${style.border} ${style.bg} ${style.text}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                          {severity}
                        </span>

                        <span className="mono text-[11px] uppercase border border-[#263140] bg-[#0B0F14] text-[#8B98A8] px-2 py-0.5 rounded-[4px]">
                          {finding.layer}
                        </span>
                      </div>

                      <div className="text-[14px] font-medium text-[#E6EDF3] line-clamp-2 leading-snug">
                        {finding.title}
                      </div>

                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 overflow-hidden">
                          {(finding.clauses || []).slice(0, 2).map((clause, idx) => (
                            <span
                              key={idx}
                              className="mono text-[11px] border border-[#263140] bg-[#0B0F14] text-[#8B98A8] px-1.5 py-0.5 rounded-[4px] truncate"
                            >
                              {clause.ref}
                            </span>
                          ))}
                          {(finding.clauses?.length || 0) > 2 && (
                            <span className="mono text-[11px] text-[#8B98A8]">
                              +{finding.clauses.length - 2}
                            </span>
                          )}
                        </div>

                        <span
                          className={`text-[11px] font-medium px-2 py-0.5 rounded-[4px] shrink-0 border ${
                            isFixed
                              ? 'bg-[#3DDC97]/15 text-[#3DDC97] border-[#3DDC97]/40'
                              : 'bg-[#0B0F14] text-[#8B98A8] border-[#263140]'
                          }`}
                        >
                          {isFixed ? 'Verified fixed' : 'Open'}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            {/* Right Column: Finding Detail Panel */}
            <section
              className="lg:col-span-7 bg-[#121821] border border-[#263140] rounded-[10px] p-4 flex flex-col gap-3 sticky top-14 shadow-lg max-h-[calc(100vh-12rem)] overflow-y-auto"
              aria-label="Finding detail"
            >
              {selectedFinding ? (
                <>
                  {/* 1. Title and Severity Header */}
                  <div className="flex flex-col gap-2 pb-2.5 border-b border-[#263140]">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                      <div className="flex items-center gap-2">
                        <span className="mono text-[13px] bg-[#19212C] border border-[#263140] text-[#E6EDF3] px-2.5 py-1 rounded-[5px] font-semibold">
                          {selectedFinding.id}
                        </span>
                        <span className="mono text-[12px] uppercase border border-[#263140] bg-[#0B0F14] text-[#8B98A8] px-2.5 py-1 rounded-[5px]">
                          Layer: {selectedFinding.layer}
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {selectedFinding.status === 'verified_fixed' && (
                          <span className="text-[12px] font-semibold px-2.5 py-1 rounded-[5px] bg-[#3DDC97]/15 text-[#3DDC97] border border-[#3DDC97]/40">
                            Verified Fixed
                          </span>
                        )}
                        <span
                          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-[6px] text-[12px] font-semibold uppercase tracking-wider border ${
                            (SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).border
                          } ${
                            (SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).bg
                          } ${
                            (SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).text
                          }`}
                        >
                          <span
                            className={`w-2 h-2 rounded-full ${
                              (SEVERITY_STYLES[selectedFinding.severity] || SEVERITY_STYLES.low).dot
                            }`}
                          />
                          {selectedFinding.severity}
                        </span>
                      </div>
                    </div>

                    <h2 className="text-[18px] font-semibold text-[#E6EDF3] leading-snug m-0">
                      {selectedFinding.title}
                    </h2>
                  </div>

                  {/* 2. Plain English Explanation */}
                  <div className="flex flex-col gap-1.5">
                    <span className="text-[13px] uppercase font-semibold tracking-wider text-[#8B98A8]">
                      Explanation
                    </span>
                    <p className="text-[15px] leading-snug text-[#E6EDF3] m-0">
                      {selectedFinding.explanation}
                    </p>
                  </div>

                  {/* 3. Clause Chips */}
                  <div className="flex flex-col gap-2">
                    <span className="text-[13px] uppercase font-semibold tracking-wider text-[#8B98A8]">
                      Governing Legal Clauses (DPDP Act & Rules)
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {(selectedFinding.clauses || []).map((clause, idx) => {
                        const isTooltipActive = activeTooltipClause === `${selectedFinding.id}-${idx}`
                        return (
                          <div key={idx} className="relative">
                            <button
                              type="button"
                              onClick={() =>
                                setActiveTooltipClause(isTooltipActive ? null : `${selectedFinding.id}-${idx}`)
                              }
                              onMouseEnter={() => setActiveTooltipClause(`${selectedFinding.id}-${idx}`)}
                              onMouseLeave={() => setActiveTooltipClause(null)}
                              className="mono text-[13px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] hover:border-[#8B98A8] text-[#E6EDF3] px-3 py-1 rounded-[6px] transition cursor-pointer flex flex-col items-start gap-0.5 text-left max-w-full"
                            >
                              <span>{clause.ref}</span>
                              <span className="text-[#8B98A8] text-[11px] font-sans leading-tight whitespace-normal">
                                {clause.note}
                              </span>
                            </button>

                            {isTooltipActive && (
                              <div className="absolute left-0 bottom-full mb-2 z-30 w-72 p-3 bg-[#19212C] border border-[#8B98A8]/40 rounded-[8px] shadow-xl text-[13px] text-[#E6EDF3]">
                                <div className="mono font-semibold text-[#3DDC97] mb-1">{clause.ref}</div>
                                <div className="text-[#8B98A8]">{clause.note}</div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  {/* 4. Evidence Block */}
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[13px] uppercase font-semibold tracking-wider text-[#8B98A8]">
                        Technical Evidence ({selectedFinding.evidence?.kind || 'observed'})
                      </span>
                      {formatLocation(selectedFinding.evidence?.location) && (
                        <span className="mono text-[12px] text-[#8B98A8] bg-[#0B0F14] px-2 py-0.5 rounded-[4px] border border-[#263140]">
                          {formatLocation(selectedFinding.evidence?.location)}
                        </span>
                      )}
                    </div>

                    <div className="bg-[#0B0F14] border border-[#263140] rounded-[8px] p-3 flex flex-col gap-2 font-mono text-[14px]">
                      <div className="text-[#8B98A8] text-[13px] font-sans">
                        {selectedFinding.evidence?.summary}
                      </div>

                      {selectedFinding.evidence?.masked_sample && (
                        <div className="bg-[#121821] border border-[#263140] rounded-[6px] p-3 overflow-x-auto text-[#E6EDF3]">
                          <span className="text-[11px] uppercase tracking-wider text-[#8B98A8] block font-sans mb-1">
                            Masked Sample
                          </span>
                          <code className="text-[#3DDC97] break-all">
                            {selectedFinding.evidence.masked_sample}
                          </code>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 5. Fix & Verify Interactive Block */}
                  <div className="pt-3 border-t border-[#263140] flex flex-col gap-3">
                    {fixingFindingId === selectedFinding.id && (
                      <div className="bg-[#0B0F14] border border-[#263140] rounded-[8px] p-4 flex flex-col gap-2.5">
                        <div className="flex items-center justify-between">
                          <span className="text-[13px] font-semibold text-[#3DDC97] uppercase tracking-wide">
                            Fix & Verify Sandbox Execution
                          </span>
                          <span className="mono text-[12px] text-[#8B98A8]">
                            Step {currentStepIndex + 1} of {FIX_STEPS.length}
                          </span>
                        </div>

                        <div className="flex flex-col gap-2 mt-1">
                          {FIX_STEPS.map((stepText, sIdx) => {
                            const isDone = sIdx < currentStepIndex
                            const isCurrent = sIdx === currentStepIndex

                            return (
                              <div key={sIdx} className="flex items-center gap-3 text-[14px]">
                                {isDone ? (
                                  <svg className="w-4 h-4 text-[#3DDC97] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                  </svg>
                                ) : isCurrent ? (
                                  <span className="w-4 h-4 rounded-full border-2 border-[#3DDC97] border-t-transparent animate-spin shrink-0" />
                                ) : (
                                  <span className="w-4 h-4 rounded-full border border-[#263140] bg-[#19212C] shrink-0" />
                                )}
                                <span className={isDone ? 'text-[#3DDC97]' : isCurrent ? 'text-[#E6EDF3] font-medium' : 'text-[#8B98A8]'}>
                                  {stepText}
                                </span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {showResult && (
                      <div className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-center justify-between gap-2 bg-[#19212C] border border-[#263140] rounded-[8px] p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge label="Re-scan passed" passed={fix.rescan_passed} />
                            <StatusBadge label="Tests passed" passed={fix.tests_passed} />
                            <StatusBadge label="Verified" passed={fix.verified} />
                          </div>
                          {fix.score_before != null && fix.score_after != null && (
                            <span className="mono text-[12px] text-[#8B98A8]">
                              Score {fix.score_before} → {fix.score_after}
                            </span>
                          )}
                        </div>

                        {sampleMode ? (
                          <span className="self-start text-[12px] font-semibold px-2.5 py-1 rounded-[5px] bg-[#FF9F43]/15 text-[#FF9F43] border border-[#FF9F43]/30">
                            Simulated (sample data)
                          </span>
                        ) : fixMode?.mode === 'cached_golden' ? (
                          <div className="flex flex-wrap items-center gap-2 text-[13px] px-3 py-2 rounded-[6px] bg-[#FF9F43]/15 text-[#FF9F43] border border-[#FF9F43]/30">
                            <span className="font-semibold">Cached golden patch mode</span>
                            <span>
                              {fixMode.fallbackReason
                                ? `Live run could not finish: ${fixMode.fallbackReason}`
                                : 'Replayed from a saved verified run, not run just now.'}
                            </span>
                          </div>
                        ) : null}

                        {fix.verified ? (
                          <div className="flex items-center gap-2 text-[#3DDC97] text-[14px] font-medium bg-[#3DDC97]/10 px-3 py-2 rounded-[6px] border border-[#3DDC97]/30">
                            <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                            <span>
                              {sampleMode
                                ? 'Simulated. No real re-scan or tests were run.'
                                : fixMode?.mode === 'cached_golden'
                                ? 'Verified in a saved run. It was not run just now.'
                                : "Verified. Re-scan passed and the app's tests still pass."}
                            </span>
                          </div>
                        ) : (
                          <div className="text-[#FF5C5C] text-[14px] font-medium bg-[#FF5C5C]/10 px-3 py-2 rounded-[6px] border border-[#FF5C5C]/30">
                            Not verified.
                            {fix.rescan_passed === false && ' The problem is still found after the fix.'}
                            {fix.tests_passed === false && " The app's tests failed."} The finding stays open.
                          </div>
                        )}

                        {fix.diff && (
                          <div className="flex flex-col gap-1.5">
                            <span className="text-[13px] uppercase font-semibold tracking-wider text-[#8B98A8]">
                              Patch (unified diff)
                            </span>
                            <DiffViewer diffText={fix.diff} />
                          </div>
                        )}

                        {!sampleMode && fix.verified && fix.diff && (
                          <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-[#8B98A8]">
                            <span>Verified on a sandbox copy. Your original code is unchanged. Download the patch to apply it.</span>
                            <div className="flex items-center gap-2 shrink-0">
                              <button
                                type="button"
                                onClick={() => copyDiff(selectedFinding)}
                                className="px-3 py-1 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#E6EDF3] text-[13px] cursor-pointer"
                              >
                                {copyState?.id === selectedFinding.id ? (copyState.ok ? 'Copied' : 'Copy failed') : 'Copy diff'}
                              </button>
                              <button
                                type="button"
                                onClick={() => downloadPatch(selectedFinding)}
                                className="px-3 py-1 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#E6EDF3] text-[13px] cursor-pointer"
                              >
                                Download patch
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {selectedFinding.status !== 'verified_fixed' && (
                      <div className="flex items-center justify-between w-full gap-4">
                        <div className="flex flex-col">
                          <span className="text-[14px] text-[#E6EDF3] font-medium">
                            {fix.available
                              ? sampleMode
                                ? 'Simulated fix (sample data)'
                                : 'Automated verified fix available'
                              : 'This finding needs a manual change'}
                          </span>
                          <span className="text-[13px] text-[#8B98A8]">
                            {fix.available
                              ? sampleMode
                                ? 'No real sandbox run happens in sample mode'
                                : 'Runs on a sandbox copy: patch, re-scan, then the app\'s tests'
                              : 'No patch template exists for it yet'}
                          </span>
                        </div>
                        {fix.available ? (
                          <button
                            type="button"
                            disabled={fixingFindingId !== null}
                            onClick={() => handleFixAndVerify(selectedFinding)}
                            className="px-5 py-2 rounded-[6px] bg-[#3DDC97] hover:bg-[#32c283] disabled:opacity-50 text-[#0B0F14] font-semibold text-[15px] transition cursor-pointer shadow flex items-center gap-2 shrink-0"
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
                            </svg>
                            Fix and verify
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled
                            className="px-5 py-2 rounded-[6px] bg-[#19212C] border border-[#263140] text-[#8B98A8] font-semibold text-[15px] cursor-not-allowed shrink-0"
                          >
                            No automated fix yet
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="text-center py-12 text-[#8B98A8]">
                  Select a finding to inspect evidence and legal clauses.
                </div>
              )}
            </section>
          </div>
        )}

        {/* 5. Tab 2: Notice vs Runtime */}
        {activeTab === 'notice_drift' && !scanData.notice_drift && (
          <section
            className="bg-[#121821] border border-[#263140] rounded-[10px] p-8 text-center flex flex-col gap-2"
            aria-label="Notice vs Runtime Truth"
          >
            <h2 className="text-[18px] font-semibold text-[#E6EDF3] m-0">No drift data yet</h2>
            <p className="text-[14px] text-[#8B98A8] m-0">
              {hasScan
                ? 'The engine returned no Notice vs Runtime data for this scan.'
                : 'Run a scan to compare the privacy notice with what the app handles.'}
            </p>
          </section>
        )}

        {activeTab === 'notice_drift' && scanData.notice_drift && (
          <section className="flex flex-col gap-6" aria-label="Notice vs Runtime Truth">
            <div className="bg-[#121821] border border-[#263140] rounded-[10px] p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-3">
                  <span className="w-3.5 h-3.5 rounded-full bg-[#FF5C5C] animate-pulse shrink-0" />
                  <h2 className="text-[22px] font-bold text-[#FF5C5C] m-0 leading-tight">
                    {undeclaredCount} of {totalUniqueFields} data fields are collected but not disclosed
                  </h2>
                </div>
                <p className="text-[14px] text-[#8B98A8] m-0">
                  Notice duties: Act s5, Rule 3 (standalone plain language notice itemising all personal data and specific purposes).
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <span className="mono text-[13px] bg-[#0B0F14] border border-[#263140] px-3 py-1.5 rounded-[6px] text-[#8B98A8]">
                  Public Notice: /notice
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
              <div className="lg:col-span-5 bg-[#121821] border border-[#263140] rounded-[10px] p-5 flex flex-col gap-4">
                <div className="flex items-center justify-between pb-3 border-b border-[#263140]">
                  <div className="flex flex-col">
                    <span className="text-[16px] font-semibold text-[#E6EDF3]">
                      What the privacy notice says we collect
                    </span>
                    <span className="text-[13px] text-[#8B98A8]">
                      Declared personal data fields in /notice
                    </span>
                  </div>
                  <span className="mono text-[12px] bg-[#3DDC97]/15 text-[#3DDC97] border border-[#3DDC97]/30 px-2 py-0.5 rounded-[4px] font-semibold">
                    {declaredList.length} declared
                  </span>
                </div>

                <div className="flex flex-col gap-2.5">
                  {declaredList.map((field, idx) => (
                    <div
                      key={idx}
                      className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3.5 flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2.5">
                        <span className="w-2 h-2 rounded-full bg-[#3DDC97]" />
                        <span className="mono text-[15px] font-semibold text-[#E6EDF3]">
                          {field}
                        </span>
                      </div>
                      <span className="text-[12px] text-[#3DDC97] font-medium bg-[#3DDC97]/10 px-2 py-0.5 rounded-[4px]">
                        Declared in notice
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="lg:col-span-7 bg-[#121821] border border-[#263140] rounded-[10px] p-5 flex flex-col gap-4">
                <div className="flex items-center justify-between pb-3 border-b border-[#263140]">
                  <div className="flex flex-col">
                    <span className="text-[16px] font-semibold text-[#E6EDF3]">
                      What the app really handles
                    </span>
                    <span className="text-[13px] text-[#8B98A8]">
                      Observed in database, API responses, and network requests
                    </span>
                  </div>
                  <span className="mono text-[12px] bg-[#19212C] border border-[#263140] text-[#E6EDF3] px-2 py-0.5 rounded-[4px] font-semibold">
                    {observedList.length} observed
                  </span>
                </div>

                <div className="flex flex-col gap-3">
                  {observedList.map((item, idx) => {
                    const isUndeclared = undeclaredList.includes(item.field)

                    return (
                      <div
                        key={idx}
                        className={`rounded-[8px] p-4 border flex flex-col gap-2.5 transition ${
                          isUndeclared
                            ? 'bg-[#FF5C5C]/10 border-[#FF5C5C]/40'
                            : 'bg-[#19212C] border-[#263140]'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2.5">
                            <span
                              className={`w-2.5 h-2.5 rounded-full ${
                                isUndeclared ? 'bg-[#FF5C5C]' : 'bg-[#3DDC97]'
                              }`}
                            />
                            <span
                              className={`mono text-[16px] font-bold ${
                                isUndeclared ? 'text-[#FF5C5C]' : 'text-[#E6EDF3]'
                              }`}
                            >
                              {item.field}
                            </span>
                          </div>

                          {isUndeclared ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[5px] text-[12px] font-bold bg-[#FF5C5C] text-[#0B0F14] tracking-wide uppercase shadow">
                              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                              </svg>
                              Not in the notice
                            </span>
                          ) : (
                            <span className="text-[12px] text-[#3DDC97] font-medium bg-[#3DDC97]/15 px-2 py-0.5 rounded-[4px] border border-[#3DDC97]/30">
                              Declared
                            </span>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <span className="text-[12px] text-[#8B98A8] font-sans">
                            Observed location:
                          </span>
                          {(item.where || []).map((loc, wIdx) => {
                            let tagStyle = 'bg-[#0B0F14] text-[#8B98A8] border-[#263140]'
                            if (loc.startsWith('db:')) tagStyle = 'bg-[#6FA8DC]/10 text-[#6FA8DC] border-[#6FA8DC]/30'
                            else if (loc.startsWith('api:')) tagStyle = 'bg-[#3DDC97]/10 text-[#3DDC97] border-[#3DDC97]/30'
                            else if (loc.startsWith('request:')) tagStyle = 'bg-[#FF9F43]/10 text-[#FF9F43] border-[#FF9F43]/30'

                            return (
                              <span
                                key={wIdx}
                                className={`mono text-[12px] border px-2.5 py-0.5 rounded-[4px] ${tagStyle}`}
                              >
                                {loc}
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 6. Tab 3: Data Flow */}
        {activeTab === 'data_flow' && !scanData.notice_drift && (
          <section
            className="bg-[#121821] border border-[#263140] rounded-[10px] p-8 text-center flex flex-col gap-2"
            aria-label="Data Flow Map"
          >
            <h2 className="text-[18px] font-semibold text-[#E6EDF3] m-0">No data flow yet</h2>
            <p className="text-[14px] text-[#8B98A8] m-0">
              {hasScan
                ? 'The engine returned no data flow information for this scan.'
                : 'Run a scan to see how personal data moves between the database, API, frontend and third parties.'}
            </p>
          </section>
        )}

        {activeTab === 'data_flow' && scanData.notice_drift && (
          <section className="bg-[#121821] border border-[#263140] rounded-[10px] p-6 flex flex-col gap-6" aria-label="Data Flow Map">
            <div className="flex flex-col gap-1">
              <h2 className="text-[18px] font-semibold text-[#E6EDF3] m-0">
                Cross-Layer Data Flow Architecture
              </h2>
              <p className="text-[13px] text-[#8B98A8] m-0">
                Flow of personal data across Database, Backend API, Frontend, and Third Parties. Red channels indicate undeclared drift.
              </p>
            </div>

            <div className="w-full bg-[#0B0F14] border border-[#263140] rounded-[8px] p-6 overflow-x-auto">
              <svg className="w-full min-w-[700px] h-[220px]" viewBox="0 0 800 200">
                <defs>
                  <marker id="arrow-green" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                    <path d="M 0 0 L 8 4 L 0 8 z" fill="#3DDC97" />
                  </marker>
                  <marker id="arrow-red" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                    <path d="M 0 0 L 8 4 L 0 8 z" fill="#FF5C5C" />
                  </marker>
                </defs>

                <rect x="20" y="60" width="140" height="80" rx="8" fill="#121821" stroke="#263140" strokeWidth="1.5" />
                <text x="90" y="95" fill="#E6EDF3" fontSize="14" fontWeight="600" textAnchor="middle">Database</text>
                <text x="90" y="115" fill="#8B98A8" fontSize="11" fontFamily="monospace" textAnchor="middle">SQLite / demo.db</text>

                <path d="M 160 100 L 250 100" stroke="#FF5C5C" strokeWidth="2" markerEnd="url(#arrow-red)" />
                <text x="205" y="90" fill="#FF5C5C" fontSize="11" fontFamily="monospace" textAnchor="middle">aadhaar, pan</text>

                <rect x="260" y="60" width="140" height="80" rx="8" fill="#121821" stroke="#263140" strokeWidth="1.5" />
                <text x="330" y="95" fill="#E6EDF3" fontSize="14" fontWeight="600" textAnchor="middle">Backend API</text>
                <text x="330" y="115" fill="#8B98A8" fontSize="11" fontFamily="monospace" textAnchor="middle">:8000 / FastAPI</text>

                <path d="M 400 100 L 490 100" stroke="#FF5C5C" strokeWidth="2" markerEnd="url(#arrow-red)" />
                <text x="445" y="90" fill="#FF5C5C" fontSize="11" fontFamily="monospace" textAnchor="middle">dob, aadhaar</text>

                <rect x="500" y="60" width="140" height="80" rx="8" fill="#121821" stroke="#263140" strokeWidth="1.5" />
                <text x="570" y="95" fill="#E6EDF3" fontSize="14" fontWeight="600" textAnchor="middle">Frontend</text>
                <text x="570" y="115" fill="#8B98A8" fontSize="11" fontFamily="monospace" textAnchor="middle">:5173 / React</text>

                <path d="M 640 100 L 710 100" stroke="#FF5C5C" strokeWidth="2" markerEnd="url(#arrow-red)" />
                <text x="675" y="90" fill="#FF5C5C" fontSize="11" fontFamily="monospace" textAnchor="middle">tracker (V5)</text>

                <rect x="720" y="60" width="70" height="80" rx="8" fill="#121821" stroke="#FF5C5C" strokeWidth="1.5" />
                <text x="755" y="95" fill="#FF5C5C" fontSize="13" fontWeight="600" textAnchor="middle">3rd Party</text>
                <text x="755" y="115" fill="#8B98A8" fontSize="10" fontFamily="monospace" textAnchor="middle">Facebook</text>
              </svg>
            </div>
          </section>
        )}
      </main>

      {/* 7. Footer */}
      <footer className="border-t border-[#263140] py-4 px-6 text-center text-[13px] text-[#8B98A8] bg-[#0B0F14] print:hidden">
        DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027.
      </footer>
    </div>
  )
}
