'use client';

import React, { useState } from 'react';
import { 
  Users, 
  Mail, 
  ShieldCheck, 
  Sparkles, 
  ExternalLink,
  Code2,
  Award,
  Globe
} from 'lucide-react';
import { DocsTeamMember } from '@/lib/docs-types';

interface DocsTeamSectionProps {
  teamName?: string;
  charter?: string;
  members: DocsTeamMember[];
  onOpenAdmin?: () => void;
  isAdmin?: boolean;
}

export const DocsTeamSection: React.FC<DocsTeamSectionProps> = ({
  teamName,
  charter,
  members,
  onOpenAdmin,
  isAdmin
}) => {
  return (
    <section className="w-full max-w-6xl mx-auto px-4 py-8 space-y-10 animate-in fade-in duration-200" id="team">
      
      {/* Team Header & Charter */}
      <div className="text-center space-y-3 max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold border bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-400 shadow-xs"
        >
          <Users className="w-3.5 h-3.5" />
          <span>Engineering Leadership & AI Architecture</span>
        </div>

        <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--foreground)]">
          {teamName || "LORE Core Systems & AI Architecture"}
        </h2>

        <p className="text-sm sm:text-base text-[var(--muted-foreground)] font-medium leading-relaxed">
          {charter || "Pioneering deterministic cryptographic governance, zero-knowledge compliance verification, and sovereign enterprise knowledge operations."}
        </p>

        {isAdmin && onOpenAdmin && (
          <div className="pt-2">
            <button
              onClick={onOpenAdmin}
              className="text-xs text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 underline font-semibold cursor-pointer"
            >
              ⚙️ Edit Team Members in Admin Panel
            </button>
          </div>
        )}
      </div>

      {/* Grid of Uniform Member Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-8">
        {members.map((member) => (
          <TeamMemberCard key={member.id} member={member} />
        ))}
      </div>

      {/* Team Values & Commitments Bar */}
      <div className="p-6 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm backdrop-blur-md grid grid-cols-1 sm:grid-cols-3 gap-6 text-center"
      >
        <div className="space-y-1.5">
          <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-500/10 text-[#7c6fd6] dark:text-[#a59bf3] flex items-center justify-center mx-auto mb-2">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <h4 className="font-bold text-sm text-[var(--foreground)]">Zero Compromise on Truth</h4>
          <p className="text-xs text-[var(--muted-foreground)]">
            Every AI statement backed by deterministic, page-exact citations.
          </p>
        </div>

        <div className="space-y-1.5 border-t sm:border-t-0 sm:border-x border-[var(--border)] pt-4 sm:pt-0">
          <div className="w-8 h-8 rounded-full bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mx-auto mb-2">
            <Code2 className="w-4 h-4" />
          </div>
          <h4 className="font-bold text-sm text-[var(--foreground)]">100% Engineering Density</h4>
          <p className="text-xs text-[var(--muted-foreground)]">
            Built from first principles: PyMuPDF C++, Noir circuits, and KùzuDB graphs.
          </p>
        </div>

        <div className="space-y-1.5 border-t sm:border-t-0 border-[var(--border)] pt-4 sm:pt-0">
          <div className="w-8 h-8 rounded-full bg-purple-100 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400 flex items-center justify-center mx-auto mb-2">
            <Award className="w-4 h-4" />
          </div>
          <h4 className="font-bold text-sm text-[var(--foreground)]">Open-Standard Interoperable</h4>
          <p className="text-xs text-[var(--muted-foreground)]">
            Native Model Context Protocol (MCP) server supporting Claude, Cursor & Windsurf.
          </p>
        </div>
      </div>

    </section>
  );
};

interface TeamMemberCardProps {
  member: DocsTeamMember;
}

const TeamMemberCard: React.FC<TeamMemberCardProps> = ({ member }) => {
  const [imgError, setImgError] = useState(false);

  // Fallback avatar generator
  const initials = member.full_name
    .split(' ')
    .map(n => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  return (
    <div className="group rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] p-6 flex flex-col justify-between hover:border-blue-400 dark:hover:border-[#7c6fd6]/50 hover:shadow-xl shadow-slate-200/50 dark:shadow-none transition-all duration-200 relative overflow-hidden"
    >
      {/* Top subtle glow */}
      <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/5 rounded-full blur-2xl group-hover:bg-[#5f52c4]/10 transition-colors pointer-events-none" />

      <div className="space-y-5">
        
        {/* Uniform Profile Picture Frame */}
        <div className="flex items-center gap-4">
          <div className="relative w-20 h-20 rounded-2xl overflow-hidden border-2 shadow-md shrink-0 flex items-center justify-center bg-[var(--muted)] border-sky-400/40"
          >
            {!imgError && member.avatar_url ? (
              <img
                src={member.avatar_url}
                alt={member.full_name}
                className="w-full h-full object-cover aspect-square transition-transform duration-300 group-hover:scale-105"
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center font-extrabold text-xl bg-gradient-to-br from-blue-600 to-indigo-700 text-white select-none">
                {initials}
              </div>
            )}
          </div>

          {/* Member Name & Role */}
          <div className="space-y-1">
            <h3 className="font-extrabold text-lg text-[var(--foreground)] group-hover:text-blue-600 dark:group-hover:text-[#a59bf3] transition-colors">
              {member.full_name}
            </h3>
            <p className="text-xs font-semibold text-[#7c6fd6] dark:text-[#a59bf3]">
              {member.role}
            </p>
            <a
              href={`mailto:${member.email}`}
              className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white transition-colors"
            >
              <Mail className="w-3 h-3 text-slate-400" />
              <span className="truncate max-w-[170px]">{member.email}</span>
            </a>
          </div>
        </div>

        {/* Bio */}
        <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed font-normal">
          {member.bio}
        </p>

        {/* Skills Chips */}
        {member.skills && member.skills.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {member.skills.map((skill, i) => (
              <span
                key={i}
                className="px-2 py-0.5 rounded-md text-[10px] font-mono font-medium bg-[var(--muted)] text-[var(--foreground)] border border-[var(--border)]"
              >
                {skill}
              </span>
            ))}
          </div>
        )}

      </div>

      {/* Social / Email Links Footer */}
      <div className="mt-6 pt-4 border-t border-[var(--border)] flex items-center justify-between text-xs text-[var(--muted-foreground)]">
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500">
          Core Contributor
        </span>

        <div className="flex items-center gap-2">
          {member.github && (
            <a
              href={member.github}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1.5 rounded-lg border border-[var(--border)] hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors text-[var(--muted-foreground)]"
              title="GitHub Profile"
            >
              <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
              </svg>
            </a>
          )}
          {member.linkedin && (
            <a
              href={member.linkedin}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1.5 rounded-lg border border-[var(--border)] hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors text-[var(--muted-foreground)]"
              title="LinkedIn Profile"
            >
              <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
                <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/>
              </svg>
            </a>
          )}
          <a
            href={`mailto:${member.email}`}
            className="p-1.5 rounded-lg border border-[var(--border)] hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors text-[var(--muted-foreground)]"
            title="Contact by Email"
          >
            <Mail className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

    </div>
  );
};
