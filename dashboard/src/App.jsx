import React, { useState, useEffect, useRef } from 'react'
import sampleScan from './sample-scan.json'

// Severity rank for sorting: critical first
const SEVERITY_ORDER = {
  critical: 1,
  high: 2,
  medium: 3,
  low: 4
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

function formatLocation(loc) {
  if (!loc) return null
  if (loc.file) return `${loc.file}${loc.line ? `:${loc.line}` : ''}`
  if (loc.url) return loc.url
  if (loc.table) return `${loc.table}${loc.column ? `.${loc.column}` : ''}`
  return null
}

export default function App() {
  const [scanData] = useState(sampleScan)
  const [activeTab, setActiveTab] = useState('findings')

  // Sort findings: critical first, then high, medium, low
  const sortedFindings = [...(scanData.findings || [])].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] || 99) - (SEVERITY_ORDER[b.severity] || 99)
  )

  const [selectedFindingId, setSelectedFindingId] = useState(
    sortedFindings.length > 0 ? sortedFindings[0].id : null
  )

  const [activeTooltipClause, setActiveTooltipClause] = useState(null)
  const listRef = useRef(null)

  const selectedFinding = sortedFindings.find((f) => f.id === selectedFindingId) || sortedFindings[0]

  // Keyboard navigation: ArrowUp and ArrowDown navigate the list
  useEffect(() => {
    function handleKeyDown(e) {
      if (!sortedFindings.length) return
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
  }, [selectedFindingId, sortedFindings])

  const score = scanData.score ?? 0
  const scoreColor = score < 50 ? '#FF5C5C' : score < 80 ? '#FF9F43' : '#3DDC97'

  return (
    <div className="min-h-screen bg-[#0B0F14] text-[#E6EDF3] flex flex-col font-sans">
      {/* 1. Sticky Top Bar */}
      <header className="sticky top-0 z-50 bg-[#121821] border-b border-[#263140] px-6 py-3.5">
        <div className="max-w-[1280px] mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <h1 className="text-[24px] font-semibold tracking-tight text-[#E6EDF3] m-0">
              DPDP Lens
            </h1>
            <span className="mono text-[14px] bg-[#19212C] border border-[#263140] px-2.5 py-1 rounded-[6px] text-[#8B98A8]">
              target: {scanData.target}
            </span>
            <span className="text-[13px] text-[#8B98A8] hidden sm:inline">
              scanned: {new Date(scanData.scanned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-[13px] text-[#8B98A8] border border-[#263140] px-3 py-1 rounded-[6px] hidden md:inline">
              Readiness report, not a compliance certificate
            </span>
            <button
              type="button"
              className="px-3.5 py-1.5 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#E6EDF3] text-[14px] font-medium transition cursor-pointer"
            >
              Run scan
            </button>
            <button
              type="button"
              className="px-3.5 py-1.5 rounded-[6px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] text-[#E6EDF3] text-[14px] font-medium transition cursor-pointer"
            >
              Export report
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-[1280px] w-full mx-auto px-6 py-6 flex-1 flex flex-col gap-6">
        {/* 2. Summary Row */}
        <section className="grid grid-cols-1 md:grid-cols-12 gap-4">
          {/* Score Gauge Card */}
          <div className="md:col-span-4 bg-[#121821] border border-[#263140] rounded-[10px] p-5 flex items-center gap-6">
            <div className="relative w-24 h-24 flex items-center justify-center shrink-0">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                <circle
                  cx="18"
                  cy="18"
                  r="14"
                  fill="none"
                  stroke="#19212C"
                  strokeWidth="3.5"
                />
                <circle
                  cx="18"
                  cy="18"
                  r="14"
                  fill="none"
                  stroke={scoreColor}
                  strokeWidth="3.5"
                  strokeDasharray={`${(score / 100) * 88} 88`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-[34px] font-bold tracking-tight" style={{ color: scoreColor }}>
                  {score}
                </span>
              </div>
            </div>

            <div className="flex flex-col">
              <div className="text-[13px] uppercase tracking-wider text-[#8B98A8] font-semibold">
                Readiness Score
              </div>
              <div className="text-[20px] font-semibold text-[#E6EDF3] mt-0.5">
                {score < 50 ? 'Needs Attention' : score < 80 ? 'Moderate' : 'Good Posture'}
              </div>
              <div className="text-[13px] text-[#8B98A8] mt-1">
                Readiness score. Higher is better.
              </div>
            </div>
          </div>

          {/* Severity Counts Cards */}
          <div className="md:col-span-8 bg-[#121821] border border-[#263140] rounded-[10px] p-5 grid grid-cols-2 sm:grid-cols-4 gap-3 items-center">
            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#FF5C5C]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#FF5C5C] tracking-wide">Critical</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.critical ?? 0}
              </span>
            </div>

            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#FF9F43]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#FF9F43] tracking-wide">High</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.high ?? 0}
              </span>
            </div>

            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#F5C451]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#F5C451] tracking-wide">Medium</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.medium ?? 0}
              </span>
            </div>

            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#6FA8DC]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#6FA8DC] tracking-wide">Low</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.low ?? 0}
              </span>
            </div>
          </div>
        </section>

        {/* 3. Navigation Tabs */}
        <div className="flex border-b border-[#263140] gap-8">
          <button
            type="button"
            onClick={() => setActiveTab('findings')}
            className={`pb-3 text-[16px] font-medium transition cursor-pointer flex items-center gap-2 border-b-2 ${
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
            className={`pb-3 text-[16px] font-medium transition cursor-pointer flex items-center gap-2 border-b-2 ${
              activeTab === 'notice_drift'
                ? 'border-[#3DDC97] text-[#3DDC97]'
                : 'border-transparent text-[#8B98A8] hover:text-[#E6EDF3]'
            }`}
          >
            Notice vs Runtime
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('data_flow')}
            className={`pb-3 text-[16px] font-medium transition cursor-pointer flex items-center gap-2 border-b-2 ${
              activeTab === 'data_flow'
                ? 'border-[#3DDC97] text-[#3DDC97]'
                : 'border-transparent text-[#8B98A8] hover:text-[#E6EDF3]'
            }`}
          >
            Data Flow
          </button>
        </div>

        {/* 4. Tab 1: Findings Split View (List ~40%, Detail ~60%) */}
        {activeTab === 'findings' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column: Findings List (40% width on desktop) */}
            <section
              ref={listRef}
              className="lg:col-span-5 bg-[#121821] border border-[#263140] rounded-[10px] overflow-hidden"
              aria-label="Findings list"
            >
              <div className="px-4 py-3 border-b border-[#263140] flex items-center justify-between">
                <span className="text-[14px] font-semibold text-[#E6EDF3]">
                  Findings ({sortedFindings.length})
                </span>
                <span className="text-[12px] text-[#8B98A8]">
                  Use ↑ ↓ to navigate
                </span>
              </div>

              <div className="divide-y divide-[#263140]">
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
                      className={`p-3.5 transition cursor-pointer flex flex-col gap-2 border-l-4 ${
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

                      <div className="text-[15px] font-medium text-[#E6EDF3] line-clamp-2 leading-snug">
                        {finding.title}
                      </div>

                      <div className="flex items-center justify-between gap-2 pt-1">
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
                              ? 'bg-[#3DDC97]/10 text-[#3DDC97] border-[#3DDC97]/30'
                              : 'bg-[#0B0F14] text-[#8B98A8] border-[#263140]'
                          }`}
                        >
                          {isFixed ? 'Verified' : 'Open'}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            {/* Right Column: Finding Detail Panel (~60% width on desktop) */}
            <section
              className="lg:col-span-7 bg-[#121821] border border-[#263140] rounded-[10px] p-6 flex flex-col gap-5 sticky top-20 shadow-lg"
              aria-label="Finding detail"
            >
              {selectedFinding ? (
                <>
                  {/* 1. Title and Severity Header */}
                  <div className="flex flex-col gap-2.5 pb-4 border-b border-[#263140]">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <span className="mono text-[13px] bg-[#19212C] border border-[#263140] text-[#E6EDF3] px-2.5 py-1 rounded-[5px] font-semibold">
                          {selectedFinding.id}
                        </span>
                        <span className="mono text-[12px] uppercase border border-[#263140] bg-[#0B0F14] text-[#8B98A8] px-2.5 py-1 rounded-[5px]">
                          Layer: {selectedFinding.layer}
                        </span>
                      </div>

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

                    <h2 className="text-[20px] font-semibold text-[#E6EDF3] leading-snug m-0">
                      {selectedFinding.title}
                    </h2>
                  </div>

                  {/* 2. Plain English Explanation */}
                  <div className="flex flex-col gap-1.5">
                    <span className="text-[13px] uppercase font-semibold tracking-wider text-[#8B98A8]">
                      Explanation
                    </span>
                    <p className="text-[16px] leading-relaxed text-[#E6EDF3] m-0">
                      {selectedFinding.explanation}
                    </p>
                  </div>

                  {/* 3. Clause Chips with interactive note tooltips */}
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
                              className="mono text-[13px] border border-[#263140] bg-[#19212C] hover:bg-[#263140] hover:border-[#8B98A8] text-[#E6EDF3] px-3 py-1.5 rounded-[6px] transition cursor-pointer flex items-center gap-2"
                            >
                              <span>{clause.ref}</span>
                              <span className="text-[#8B98A8] text-[11px] font-sans">
                                ({clause.note})
                              </span>
                            </button>

                            {/* Tooltip Card */}
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

                  {/* 4. Evidence Block (Masked Only) */}
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

                    <div className="bg-[#0B0F14] border border-[#263140] rounded-[8px] p-4 flex flex-col gap-3 font-mono text-[14px]">
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

                  {/* 5. Fix Block */}
                  <div className="pt-2 border-t border-[#263140] flex items-center justify-between">
                    {selectedFinding.status === 'verified_fixed' ? (
                      <div className="flex items-center gap-2 text-[#3DDC97] text-[14px] font-medium bg-[#3DDC97]/10 px-3.5 py-2 rounded-[6px] border border-[#3DDC97]/30">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                        </svg>
                        <span>Verified. Re-scan passed and the app's tests still pass.</span>
                      </div>
                    ) : selectedFinding.fix?.available ? (
                      <div className="flex items-center justify-between w-full">
                        <span className="text-[13px] text-[#8B98A8]">
                          Automated deterministic patch template ready
                        </span>
                        <button
                          type="button"
                          className="px-4 py-2 rounded-[6px] bg-[#3DDC97] hover:bg-[#32c283] text-[#0B0F14] font-semibold text-[14px] transition cursor-pointer shadow"
                        >
                          Fix and verify
                        </button>
                      </div>
                    ) : (
                      <span className="text-[13px] text-[#8B98A8] italic">
                        Manual architectural remediation required (no automated patch template available).
                      </span>
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
      </main>

      {/* 5. Footer */}
      <footer className="border-t border-[#263140] py-4 px-6 text-center text-[13px] text-[#8B98A8] bg-[#0B0F14]">
        DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027.
      </footer>
    </div>
  )
}
