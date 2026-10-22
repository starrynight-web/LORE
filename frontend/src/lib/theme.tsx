'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEYS = ['lore_theme', 'lore-theme'];

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<Theme>('light');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    try {
      let stored: Theme | null = null;
      for (const k of STORAGE_KEYS) {
        const val = localStorage.getItem(k) as Theme | null;
        if (val === 'dark' || val === 'light') {
          stored = val;
          break;
        }
      }

      if (stored === 'dark' || stored === 'light') {
        setThemeState(stored);
        applyTheme(stored);
      } else {
        setThemeState('light');
        applyTheme('light');
      }
    } catch (e) {
      applyTheme('light');
    }
    setMounted(true);
  }, []);

  const applyTheme = (t: Theme) => {
    const root = document.documentElement;
    if (t === 'dark') {
      root.classList.add('dark');
      root.setAttribute('data-theme', 'dark');
      root.style.colorScheme = 'dark';
      if (typeof document !== 'undefined' && document.body) {
        document.body.classList.add('dark');
        document.body.setAttribute('data-theme', 'dark');
      }
    } else {
      root.classList.remove('dark');
      root.setAttribute('data-theme', 'light');
      root.style.colorScheme = 'light';
      if (typeof document !== 'undefined' && document.body) {
        document.body.classList.remove('dark');
        document.body.setAttribute('data-theme', 'light');
      }
    }

    // Sync browser theme-color meta tag
    let metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (!metaThemeColor) {
      metaThemeColor = document.createElement('meta');
      metaThemeColor.setAttribute('name', 'theme-color');
      document.head.appendChild(metaThemeColor);
    }
    metaThemeColor.setAttribute('content', t === 'dark' ? '#0C130E' : '#FAF8F5');
  };

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
    applyTheme(newTheme);
    try {
      for (const k of STORAGE_KEYS) {
        localStorage.setItem(k, newTheme);
      }
    } catch (e) {}
  };

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
