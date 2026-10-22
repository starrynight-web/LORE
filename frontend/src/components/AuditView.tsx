'use client';

import React from 'react';
import { ShieldCheck, RotateCw } from 'lucide-react';
import { AuditEvent } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface AuditViewProps {
  events: AuditEvent[];
  onRefresh: () => void;
}

export const AuditView: React.FC<AuditViewProps> = ({
  events,
  onRefresh
}) => {
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold flex items-center gap-2 text-[var(--text-primary)]">
            <ShieldCheck className="w-5 h-5 text-[var(--brand-accent)]" />
            <span>{t('audit.title')}</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {t('audit.subtitle')}
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95 shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-primary)',
          }}
        >
          <RotateCw className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
          <span>{t('common.refresh')}</span>
        </button>
      </div>

      <div 
        className="rounded-2xl border overflow-hidden shadow-sm"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead 
              className="text-xs font-bold uppercase tracking-wider border-b"
              style={{
                backgroundColor: 'var(--table-header-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-muted)',
              }}
            >
              <tr>
                <th className="px-5 py-3.5">{t('audit.timestamp')}</th>
                <th className="px-4 py-3.5">{t('audit.action')}</th>
                <th className="px-4 py-3.5">{t('audit.actor')}</th>
                <th className="px-4 py-3.5">{t('audit.resource')}</th>
                <th className="px-5 py-3.5">{t('audit.details')}</th>
              </tr>
            </thead>
            <tbody className="divide-y font-mono text-xs" style={{ borderColor: 'var(--border-color)' }}>
              {events.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-sm font-sans text-[var(--text-muted)]">
                    No audit events recorded yet.
                  </td>
                </tr>
              ) : (
                events.map((ev) => (
                  <tr 
                    key={ev.id} 
                    className="transition-colors duration-150"
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--table-row-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    <td className="px-5 py-3.5 text-[var(--text-muted)] whitespace-nowrap">
                      {new Date(ev.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3.5">
                      <span 
                        className="px-2 py-0.5 rounded font-bold text-[11px] border"
                        style={{
                          backgroundColor: 'var(--accent-light)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--brand-accent)',
                        }}
                      >
                        {ev.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-[var(--text-primary)] font-sans font-medium">
                      {ev.username || 'System'}
                    </td>
                    <td className="px-4 py-3.5 text-[var(--text-muted)]">
                      {ev.target_type} ({ev.target_id.substring(0, 8)}...)
                    </td>
                    <td className="px-5 py-3.5 text-[var(--text-secondary)] truncate max-w-xs font-mono">
                      {JSON.stringify(ev.details)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
