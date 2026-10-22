'use client';

import React from 'react';
import { ShieldCheck, RotateCw, Clock, User, Hash } from 'lucide-react';
import { AuditEvent } from '@/lib/api';

interface AuditViewProps {
  events: AuditEvent[];
  onRefresh: () => void;
}

export const AuditView: React.FC<AuditViewProps> = ({
  events,
  onRefresh
}) => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            <span>Immutable Governance Audit Ledger</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Tamper-evident record of all uploads, OCR completions, retrieval queries, and governance decisions.
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white px-3.5 py-2 rounded-lg text-xs font-semibold border border-slate-700 transition cursor-pointer"
        >
          <RotateCw className="w-3.5 h-3.5" />
          <span>Refresh Ledger</span>
        </button>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-800/60 text-xs font-semibold uppercase tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="px-6 py-3.5">Timestamp</th>
              <th className="px-4 py-3.5">Event Type</th>
              <th className="px-4 py-3.5">Actor</th>
              <th className="px-4 py-3.5">Target</th>
              <th className="px-6 py-3.5">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 font-mono text-xs">
            {events.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-slate-500 font-sans text-sm">
                  No audit events recorded yet.
                </td>
              </tr>
            ) : (
              events.map((ev) => (
                <tr key={ev.id} className="hover:bg-slate-800/40 transition">
                  <td className="px-6 py-3.5 text-slate-400 whitespace-nowrap">
                    {new Date(ev.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3.5">
                    <span className="px-2 py-0.5 rounded font-bold text-[11px] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      {ev.event_type}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-slate-300 font-sans">
                    {ev.username || 'System'}
                  </td>
                  <td className="px-4 py-3.5 text-slate-400">
                    {ev.target_type} ({ev.target_id.substring(0, 8)}...)
                  </td>
                  <td className="px-6 py-3.5 text-slate-300 truncate max-w-xs">
                    {JSON.stringify(ev.details)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
