import React, { useState } from 'react'
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
    bg: 'bg-[#FF5C5C]/10'
  },
  high: {
    dot: 'bg-[#FF9F43]',
    text: 'text-[#FF9F43]',
    border: 'border-[#FF9F43]/30',
    bg: 'bg-[#FF9F43]/10'
  },
  medium: {
    dot: 'bg-[#F5C451]',
    text: 'text-[#F5C451]',
    border: 'border-[#F5C451]/30',
    bg: 'bg-[#F5C451]/10'
  },
  low: {
    dot: 'bg-[#6FA8DC]',
    text: 'text-[#6FA8DC]',
    border: 'border-[#6FA8DC]/30',
    bg: 'bg-[#6FA8DC]/10'
  }
}

export default function App() {
  const [scanData] = useState(sampleScan)
  const [activeTab, setActiveTab] = useState('findings')
  const [selectedFindingId, setSelectedFindingId] = useState(
    sampleScan.findings && sampleScan.findings.length > 0 ? sampleScan.findings[0].id : null
  )

  // Sort findings: critical first, then high, medium, low
  const sortedFindings = [...(scanData.findings || [])].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] || 99) - (SEVERITY_ORDER[b.severity] || 99)
  )

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
            {/* SVG Ring Gauge */}
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
            {/* Critical */}
            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#FF5C5C]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#FF5C5C] tracking-wide">Critical</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.critical ?? 0}
              </span>
            </div>

            {/* High */}
            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#FF9F43]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#FF9F43] tracking-wide">High</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.high ?? 0}
              </span>
            </div>

            {/* Medium */}
            <div className="bg-[#19212C] border border-[#263140] rounded-[8px] p-3 flex flex-col">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#F5C451]"></span>
                <span className="text-[12px] font-semibold uppercase text-[#F5C451] tracking-wide">Medium</span>
              </div>
              <span className="text-[28px] font-bold text-[#E6EDF3] mt-1">
                {scanData.counts?.medium ?? 0}
              </span>
            </div>

            {/* Low */}
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

        {/* 4. Findings List (Phase A1 Target) */}
        {activeTab === 'findings' && (
          <section className="bg-[#121821] border border-[#263140] rounded-[10px] overflow-hidden">
            <div className="px-5 py-3.5 border-b border-[#263140] flex items-center justify-between">
              <h2 className="text-[18px] font-semibold text-[#E6EDF3] m-0">
                Identified Findings ({sortedFindings.length})
              </h2>
              <span className="text-[13px] text-[#8B98A8]">
                Sorted by severity: Critical first
              </span>
            </div>

            <div className="divide-y divide-[#263140]">
              {sortedFindings.map((finding) => {
                const isSelected = selectedFindingId === finding.id
                const severity = finding.severity || 'low'
                const style = SEVERITY_STYLES[severity] || SEVERITY_STYLES.low
                const isFixed = finding.status === 'verified_fixed'

                return (
                  <div
                    key={finding.id}
                    onClick={() => setSelectedFindingId(finding.id)}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        setSelectedFindingId(finding.id)
                      }
                    }}
                    className={`p-4 transition cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-3 ${
                      isSelected ? 'bg-[#19212C]' : 'hover:bg-[#19212C]/60'
                    }`}
                  >
                    <div className="flex items-start md:items-center gap-3.5 flex-1 min-w-0">
                      {/* Severity Pill */}
                      <span
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[6px] text-[12px] font-semibold uppercase tracking-wider shrink-0 border ${style.border} ${style.bg} ${style.text}`}
                      >
                        <span className={`w-2 h-2 rounded-full ${style.dot}`} />
                        {severity}
                      </span>

                      {/* Finding Title & Layer */}
                      <div className="flex flex-col sm:flex-row sm:items-center gap-2 min-w-0">
                        <span className="text-[16px] font-medium text-[#E6EDF3] truncate">
                          {finding.title}
                        </span>
                        <span className="mono text-[11px] uppercase border border-[#263140] bg-[#0B0F14] text-[#8B98A8] px-2 py-0.5 rounded-[4px] shrink-0 self-start sm:self-auto">
                          {finding.layer}
                        </span>
                      </div>
                    </div>

                    {/* Clauses and Status */}
                    <div className="flex items-center gap-2.5 shrink-0 self-end md:self-auto">
                      {/* First two clause chips */}
                      <div className="flex items-center gap-1.5">
                        {(finding.clauses || []).slice(0, 2).map((clause, idx) => (
                          <span
                            key={idx}
                            title={clause.note}
                            className="mono text-[12px] border border-[#263140] bg-[#19212C] text-[#8B98A8] px-2 py-0.5 rounded-[4px]"
                          >
                            {clause.ref}
                          </span>
                        ))}
                        {(finding.clauses?.length || 0) > 2 && (
                          <span className="mono text-[12px] text-[#8B98A8] px-1">
                            +{finding.clauses.length - 2}
                          </span>
                        )}
                      </div>

                      {/* Status */}
                      <span
                        className={`text-[12px] font-medium px-2.5 py-1 rounded-[6px] shrink-0 border ${
                          isFixed
                            ? 'bg-[#3DDC97]/10 text-[#3DDC97] border-[#3DDC97]/30'
                            : 'bg-[#19212C] text-[#8B98A8] border-[#263140]'
                        }`}
                      >
                        {isFixed ? 'Verified Fixed' : 'Open'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}
      </main>

      {/* 5. Footer */}
      <footer className="border-t border-[#263140] py-4 px-6 text-center text-[13px] text-[#8B98A8] bg-[#0B0F14]">
        DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027.
      </footer>
    </div>
  )
}
