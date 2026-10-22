'use client';

import React from 'react';
import { Sun, Moon } from 'lucide-react';
import { useTheme } from '@/lib/theme';
import { useI18n, Language } from '@/lib/i18n';

interface ThemeToggleProps {
  compact?: boolean;
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({ compact = false }) => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  if (compact) {
    // Compact: 68x36px track, 28x28px thumb, 32px travel
    return (
      <button
        type="button"
        role="switch"
        aria-checked={isDark}
        aria-label={isDark ? "Switch to Light mode" : "Switch to Dark mode"}
        onClick={toggleTheme}
        className="relative w-[68px] h-[36px] p-1 rounded-full border transition-all duration-300 ease-out select-none cursor-pointer focus:outline-none focus-visible:ring-2 active:scale-95 flex items-center justify-between"
        style={{
          backgroundColor: 'var(--bg-surface-soft)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Background Icons */}
        <div className="absolute inset-0 flex items-center justify-between px-2.5 pointer-events-none z-0">
          <Sun 
            className={`w-3.5 h-3.5 transition-opacity duration-300 ${
              !isDark ? 'opacity-0' : 'text-[var(--text-muted)] opacity-50'
            }`} 
          />
          <Moon 
            className={`w-3.5 h-3.5 transition-opacity duration-300 ${
              isDark ? 'opacity-0' : 'text-[var(--text-muted)] opacity-50'
            }`} 
          />
        </div>

        {/* Sliding Thumb */}
        <div
          className="relative z-10 w-[28px] h-[28px] rounded-full flex items-center justify-center transition-transform duration-300 ease-out shadow-sm border"
          style={{
            transform: isDark ? 'translateX(32px)' : 'translateX(0px)',
            backgroundColor: 'var(--bg-surface)',
            borderColor: isDark ? 'var(--border-focus)' : 'var(--border-color)',
            boxShadow: isDark 
              ? '0 2px 8px rgba(34, 197, 94, 0.25)' 
              : '0 2px 6px rgba(21, 31, 22, 0.1)',
          }}
        >
          {isDark ? (
            <Moon className="w-3.5 h-3.5 text-[#22C55E]" />
          ) : (
            <Sun className="w-3.5 h-3.5 text-[#D97706]" />
          )}
        </div>
      </button>
    );
  }

  // Regular Desktop: 78x40px track, 32x32px thumb, 38px travel
  return (
    <button
      type="button"
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? "Switch to Light mode (Parrot & Cream)" : "Switch to Dark mode (Obsidian & Emerald)"}
      onClick={toggleTheme}
      className="relative w-[78px] h-[40px] p-1 rounded-full border transition-all duration-300 ease-out select-none cursor-pointer focus:outline-none focus-visible:ring-2 active:scale-95 flex items-center justify-between"
      style={{
        backgroundColor: 'var(--bg-surface-soft)',
        borderColor: 'var(--border-color)',
      }}
    >
      {/* Background Icons */}
      <div className="absolute inset-0 flex items-center justify-between px-3 pointer-events-none z-0">
        <Sun 
          className={`w-4 h-4 transition-opacity duration-300 ${
            !isDark ? 'opacity-0' : 'text-[var(--text-muted)] opacity-40'
          }`} 
        />
        <Moon 
          className={`w-4 h-4 transition-opacity duration-300 ${
            isDark ? 'opacity-0' : 'text-[var(--text-muted)] opacity-40'
          }`} 
        />
      </div>

      {/* Sliding Thumb */}
      <div
        className="relative z-10 w-[32px] h-[32px] rounded-full flex items-center justify-center transition-transform duration-300 ease-out shadow-md border"
        style={{
          transform: isDark ? 'translateX(38px)' : 'translateX(0px)',
          backgroundColor: 'var(--bg-surface)',
          borderColor: isDark ? 'var(--border-focus)' : 'var(--border-color)',
          boxShadow: isDark 
            ? '0 2px 10px rgba(34, 197, 94, 0.3)' 
            : '0 2px 8px rgba(21, 31, 22, 0.12)',
        }}
      >
        {isDark ? (
          <Moon className="w-4 h-4 text-[#22C55E]" />
        ) : (
          <Sun className="w-4 h-4 text-[#D97706]" />
        )}
      </div>
    </button>
  );
};

export const LanguageToggle: React.FC = () => {
  const { language, setLanguage } = useI18n();

  return (
    <div 
      className="inline-flex items-center p-0.5 rounded-full border transition-all duration-200 select-none"
      style={{
        backgroundColor: 'var(--bg-surface-soft)',
        borderColor: 'var(--border-color)'
      }}
      role="group"
      aria-label="Interface language selector"
    >
      <button
        type="button"
        aria-pressed={language === 'bn'}
        onClick={() => setLanguage('bn')}
        className={`px-3 py-1 text-xs font-semibold rounded-full transition-all duration-200 cursor-pointer ${
          language === 'bn'
            ? 'shadow-sm text-white'
            : 'hover:text-[var(--text-primary)]'
        }`}
        style={{
          backgroundColor: language === 'bn' ? 'var(--brand-accent)' : 'transparent',
          color: language === 'bn' ? 'var(--cta-text)' : 'var(--text-secondary)'
        }}
      >
        বাংলা
      </button>

      <button
        type="button"
        aria-pressed={language === 'en'}
        onClick={() => setLanguage('en')}
        className={`px-3 py-1 text-xs font-semibold rounded-full transition-all duration-200 cursor-pointer ${
          language === 'en'
            ? 'shadow-sm text-white'
            : 'hover:text-[var(--text-primary)]'
        }`}
        style={{
          backgroundColor: language === 'en' ? 'var(--brand-accent)' : 'transparent',
          color: language === 'en' ? 'var(--cta-text)' : 'var(--text-secondary)'
        }}
      >
        EN
      </button>
    </div>
  );
};
