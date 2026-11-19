'use client';

import React, { useState } from 'react';
import { 
  Sparkles, 
  ChevronLeft, 
  ChevronRight, 
  Layers, 
  TrendingUp, 
  CheckCircle2, 
  AlertTriangle, 
  ShieldCheck, 
  Cpu, 
  Lock, 
  ArrowRight,
  Maximize2,
  Grid
} from 'lucide-react';
import { DocsPitchSlide } from '@/lib/api';

interface DocsPitchDeckViewProps {
  slides: DocsPitchSlide[];
  title?: string;
  tagline?: string;
  searchQuery?: string;
}

export const DocsPitchDeckView: React.FC<DocsPitchDeckViewProps> = ({
  slides,
  title,
  tagline,
  searchQuery = ''
}) => {
  const [activeSlideIdx, setActiveSlideIdx] = useState(0);
  const [gridMode, setGridMode] = useState(false);

  // Filter slides if search query is provided
  const filteredSlides = slides.filter(slide => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      slide.title.toLowerCase().includes(q) ||
      slide.subtitle.toLowerCase().includes(q) ||
      slide.badge.toLowerCase().includes(q) ||
      slide.points.some(p => p.toLowerCase().includes(q))
    );
  });

  const currentSlide = filteredSlides[activeSlideIdx] || filteredSlides[0] || slides[0];

  const handleNext = () => {
    if (activeSlideIdx < filteredSlides.length - 1) {
      setActiveSlideIdx(activeSlideIdx + 1);
    }
  };

  const handlePrev = () => {
    if (activeSlideIdx > 0) {
      setActiveSlideIdx(activeSlideIdx - 1);
    }
  };

  return (
    <div className="w-full max-w-6xl mx-auto px-4 py-8 space-y-8 animate-in fade-in duration-200">
      
      {/* Title & Tagline Banner */}
      <div className="text-center space-y-3 max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold border bg-blue-50 dark:bg-sky-500/10 border-blue-200 dark:border-sky-500/30 text-blue-600 dark:text-sky-400 shadow-xs"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>Y Combinator–Style Executive Pitch Deck</span>
        </div>

        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-slate-900 dark:text-white">
          {title || "LORE: The Cryptographic Truth Engine for Enterprise AI"}
        </h1>

        <p className="text-sm sm:text-base text-slate-600 dark:text-slate-400 font-medium leading-relaxed">
          {tagline || "Eliminating AI Hallucinations with Deterministic Governance, Zero-LLM Ingestion, and Selective ZK-Proofs"}
        </p>
      </div>

      {/* Controls: Mode Switch & Slide Navigation Track */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 p-2 rounded-2xl border bg-white dark:bg-slate-900/60 border-slate-200/90 dark:border-slate-800 backdrop-blur-md shadow-xs"
      >
        {/* Slide Counter & Mode Toggle */}
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono font-bold px-3 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 border border-slate-200/60 dark:border-slate-700/60">
            Slide {activeSlideIdx + 1} of {filteredSlides.length}
          </span>
          <button
            onClick={() => setGridMode(!gridMode)}
            className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold border transition-colors bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white shadow-xs"
          >
            <Grid className="w-3.5 h-3.5" />
            <span>{gridMode ? 'Presentation Mode' : 'View All Slides'}</span>
          </button>
        </div>

        {/* Thumbnail Track */}
        <div className="flex items-center gap-1.5 overflow-x-auto max-w-full pb-1 sm:pb-0">
          {filteredSlides.map((slide, idx) => (
            <button
              key={slide.id || idx}
              onClick={() => {
                setActiveSlideIdx(idx);
                setGridMode(false);
              }}
              className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                idx === activeSlideIdx && !gridMode
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20 scale-105'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-200/80 dark:border-slate-700/60'
              }`}
              title={slide.title}
            >
              {slide.number || idx + 1}
            </button>
          ))}
        </div>

        {/* Prev / Next Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={handlePrev}
            disabled={activeSlideIdx === 0 || gridMode}
            className="p-1.5 rounded-lg border bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-xs"
            aria-label="Previous Slide"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={handleNext}
            disabled={activeSlideIdx === filteredSlides.length - 1 || gridMode}
            className="p-1.5 rounded-lg border bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-xs"
            aria-label="Next Slide"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main Slide Card or Grid View */}
      {gridMode ? (
        /* Grid Mode: All Slides Overview */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredSlides.map((slide, idx) => (
            <div
              key={slide.id || idx}
              onClick={() => {
                setActiveSlideIdx(idx);
                setGridMode(false);
              }}
              className="p-5 rounded-2xl border bg-white dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 hover:border-blue-500 hover:shadow-xl dark:hover:bg-slate-800/60 transition-all cursor-pointer flex flex-col justify-between group shadow-sm"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                    SLIDE {slide.number || idx + 1}
                  </span>
                  <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    {slide.badge}
                  </span>
                </div>
                <h3 className="font-bold text-base text-slate-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                  {slide.title}
                </h3>
                <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2">
                  {slide.subtitle}
                </p>
              </div>

              {slide.stats && slide.stats.length > 0 && (
                <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs">
                  <span className="font-extrabold text-blue-600 dark:text-blue-400 text-sm">
                    {slide.stats[0].value}
                  </span>
                  <span className="text-[10px] text-slate-500 dark:text-slate-400">
                    {slide.stats[0].label}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        /* Active Slide Card (Presentation View) */
        <div className="rounded-3xl border border-slate-200 dark:border-slate-800 shadow-xl shadow-slate-200/50 dark:shadow-2xl overflow-hidden bg-white dark:bg-slate-900/80 backdrop-blur-xl transition-all"
        >
          {/* Slide Header */}
          <div className="p-6 sm:p-8 border-b border-slate-200 dark:border-slate-800/80 bg-gradient-to-r from-slate-50 via-white to-blue-50/40 dark:from-slate-900/90 dark:via-slate-900/60 dark:to-blue-950/20 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2.5">
                <span className="px-3 py-1 rounded-full text-xs font-mono font-extrabold bg-blue-50 dark:bg-blue-600/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/30">
                  SLIDE {currentSlide.number}
                </span>
                <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 uppercase tracking-wider">
                  {currentSlide.badge}
                </span>
              </div>
              <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-white tracking-tight">
                {currentSlide.title}
              </h2>
              <p className="text-sm sm:text-base text-slate-600 dark:text-slate-300 font-medium">
                {currentSlide.subtitle}
              </p>
            </div>

            {/* Quick Next Pill */}
            {activeSlideIdx < filteredSlides.length - 1 && (
              <button
                onClick={handleNext}
                className="hidden md:flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition-all shadow-lg shadow-blue-600/30 shrink-0"
              >
                <span>Next Slide</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Slide Body */}
          <div className="p-6 sm:p-10 space-y-8 bg-white dark:bg-transparent">
            
            {/* Key Stats Chips */}
            {currentSlide.stats && currentSlide.stats.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {currentSlide.stats.map((st, i) => (
                  <div
                    key={i}
                    className="p-5 rounded-2xl border border-slate-200 dark:border-slate-700/60 bg-slate-50 dark:bg-slate-800/40 relative overflow-hidden group hover:bg-white dark:hover:bg-slate-800 hover:border-blue-400 dark:hover:border-blue-500/50 hover:shadow-md transition-all"
                  >
                    <div className="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 rounded-full blur-xl group-hover:bg-blue-500/10 transition-colors" />
                    <div className="text-3xl sm:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 dark:from-blue-400 dark:via-indigo-300 dark:to-purple-400 bg-clip-text text-transparent">
                      {st.value}
                    </div>
                    <div className="text-xs font-bold text-slate-600 dark:text-slate-400 mt-1.5 uppercase tracking-wide">
                      {st.label}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Bullet Points */}
            <div className="space-y-4">
              <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                Key Strategic Takeaways
              </h4>
              <div className="grid grid-cols-1 gap-3.5">
                {currentSlide.points.map((pt, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-3.5 p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-800/20 hover:bg-white dark:hover:bg-slate-800/40 hover:border-blue-300 dark:hover:border-blue-500/30 hover:shadow-xs transition-colors"
                  >
                    <div className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-500/20 flex items-center justify-center shrink-0 mt-0.5">
                      <CheckCircle2 className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                    </div>
                    <p className="text-sm text-slate-800 dark:text-slate-100 leading-relaxed font-semibold">
                      {pt}
                    </p>
                  </div>
                ))}
              </div>
            </div>

          </div>

          {/* Slide Footer Navigation */}
          <div className="p-4 sm:p-6 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50/80 dark:bg-slate-900/60 text-xs">
            <button
              onClick={handlePrev}
              disabled={activeSlideIdx === 0}
              className="flex items-center gap-2 px-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-900 dark:hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-all font-semibold shadow-xs"
            >
              <ChevronLeft className="w-4 h-4" />
              <span>Previous</span>
            </button>

            <span className="text-slate-500 dark:text-slate-400 font-mono">
              Press left/right arrow buttons or thumbnails to navigate
            </span>

            <button
              onClick={handleNext}
              disabled={activeSlideIdx === filteredSlides.length - 1}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed text-white font-semibold transition-all shadow-md"
            >
              <span>Next</span>
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

    </div>
  );
};
