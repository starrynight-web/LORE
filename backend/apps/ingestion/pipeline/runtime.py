"""
CPU-only 16 GB RAM Runtime & Telemetry Configuration for LORE Visual Extraction.

Provides:
- Settings/env resolution for configurable rasterization DPI, pixel ceilings,
  CPU/OpenCV/OMP/Tesseract thread bounds, and conservative concurrency.
- Idempotent worker-level thread configuration (``configure_visual_cpu_runtime``).
- Cross-platform process RSS / peak RSS + tracemalloc measurement helpers.
- Thread-safe ``VisualExtractionMetrics`` tracking duration, peak memory,
  render breakdown (full-page vs clipped region), OCR counts, and failure rates.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import tracemalloc
from collections import deque
from contextlib import contextmanager
from typing import Any, Deque, Dict, Generator, List, Mapping, Optional

logger = logging.getLogger(__name__)

# Conservative CPU / 16 GB RAM defaults (DPI stays 300 for OCR fidelity, configurable via VISUAL_PDF_DPI)
DEFAULT_VISUAL_PDF_DPI = 300
DEFAULT_VISUAL_MAX_RENDER_PIXELS = 12_000_000
DEFAULT_VISUAL_CPU_THREADS = 2
DEFAULT_OPENCV_CPU_THREADS = 2
DEFAULT_TESSERACT_OMP_THREAD_LIMIT = 1
DEFAULT_VISUAL_MAX_CONCURRENCY = 1

_RUNTIME_LOCK = threading.RLock()
_LAST_RUNTIME_CONFIG: Optional[Dict[str, Any]] = None


def _get_django_setting(name: str) -> Any:
    try:
        from django.conf import settings

        if getattr(settings, "configured", False) and hasattr(settings, name):
            return getattr(settings, name)
    except Exception:
        pass
    return None


def get_setting_or_env_int(
    name: str,
    default: int,
    *,
    min_value: int = 1,
    max_value: Optional[int] = None,
) -> int:
    """Resolve an integer config cleanly from env var, Django settings, or default."""
    raw: Any = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        raw = _get_django_setting(name)
    if raw is None or str(raw).strip() == "":
        val = default
    else:
        try:
            val = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            val = default
    val = max(min_value, val)
    if max_value is not None:
        val = min(max_value, val)
    return val


def get_configured_visual_dpi(default: Optional[int] = None) -> int:
    eff_default = DEFAULT_VISUAL_PDF_DPI if default is None else default
    return get_setting_or_env_int("VISUAL_PDF_DPI", eff_default, min_value=72, max_value=600)


def get_configured_max_render_pixels(default: Optional[int] = None) -> int:
    eff_default = DEFAULT_VISUAL_MAX_RENDER_PIXELS if default is None else default
    return get_setting_or_env_int(
        "VISUAL_MAX_RENDER_PIXELS",
        eff_default,
        min_value=250_000,
        max_value=48_000_000,
    )


def get_configured_cpu_threads(default: Optional[int] = None) -> int:
    eff_default = DEFAULT_VISUAL_CPU_THREADS if default is None else default
    host_cores = os.cpu_count() or 4
    return get_setting_or_env_int(
        "VISUAL_CPU_THREADS",
        eff_default,
        min_value=1,
        max_value=max(1, host_cores),
    )


def get_configured_opencv_threads(default: Optional[int] = None) -> int:
    eff_default = DEFAULT_OPENCV_CPU_THREADS if default is None else default
    host_cores = os.cpu_count() or 4
    return get_setting_or_env_int(
        "OPENCV_CPU_THREADS",
        eff_default,
        min_value=0,
        max_value=max(1, host_cores),
    )


def get_configured_tesseract_omp_threads(default: Optional[int] = None) -> int:
    eff_default = DEFAULT_TESSERACT_OMP_THREAD_LIMIT if default is None else default
    return get_setting_or_env_int(
        "TESSERACT_OMP_THREAD_LIMIT",
        eff_default,
        min_value=1,
        max_value=8,
    )


def get_configured_visual_concurrency(default: Optional[int] = None) -> int:
    eff_default = DEFAULT_VISUAL_MAX_CONCURRENCY if default is None else default
    return get_setting_or_env_int(
        "INGESTION_VISUAL_MAX_CONCURRENCY",
        eff_default,
        min_value=1,
        max_value=16,
    )


def configure_visual_cpu_runtime(
    *,
    cpu_threads: Optional[int] = None,
    opencv_threads: Optional[int] = None,
    tesseract_omp_threads: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Apply bounded CPU thread settings for BLAS/OMP/Tesseract/OpenCV so a 16 GB
    RAM CPU host avoids thread oversubscription and memory arena bloat.
    """
    global _LAST_RUNTIME_CONFIG

    eff_cpu = get_configured_cpu_threads(cpu_threads) if cpu_threads is None else max(1, cpu_threads)
    eff_cv = get_configured_opencv_threads(opencv_threads) if opencv_threads is None else max(0, opencv_threads)
    eff_tess = (
        get_configured_tesseract_omp_threads(tesseract_omp_threads)
        if tesseract_omp_threads is None
        else max(1, tesseract_omp_threads)
    )

    with _RUNTIME_LOCK:
        env_targets = {
            "OMP_NUM_THREADS": str(eff_cpu),
            "OPENBLAS_NUM_THREADS": str(eff_cpu),
            "MKL_NUM_THREADS": str(eff_cpu),
            "VECLIB_MAXIMUM_THREADS": str(eff_cpu),
            "NUMEXPR_NUM_THREADS": str(eff_cpu),
            "OMP_THREAD_LIMIT": str(eff_tess),
            # Reduce glibc/MKL arena sprawl on multi-threaded CPU workers when present
            "MALLOC_ARENA_MAX": "2",
        }
        for key, val in env_targets.items():
            if force:
                os.environ[key] = val
            else:
                os.environ.setdefault(key, val)

        cv_applied: Optional[int] = None
        try:
            import cv2  # type: ignore

            cv2.setNumThreads(eff_cv)
            cv_applied = cv2.getNumThreads()
        except Exception:
            cv_applied = None

        cfg = {
            "cpu_threads": eff_cpu,
            "opencv_threads_requested": eff_cv,
            "opencv_threads_applied": cv_applied,
            "tesseract_omp_threads": eff_tess,
            "visual_pdf_dpi": get_configured_visual_dpi(),
            "max_render_pixels": get_configured_max_render_pixels(),
            "visual_max_concurrency": get_configured_visual_concurrency(),
        }
        _LAST_RUNTIME_CONFIG = dict(cfg)
        return cfg


def get_runtime_cpu_config() -> Dict[str, Any]:
    with _RUNTIME_LOCK:
        if _LAST_RUNTIME_CONFIG is not None:
            return dict(_LAST_RUNTIME_CONFIG)
    return configure_visual_cpu_runtime(force=False)


def get_process_memory_mb() -> Dict[str, Optional[float]]:
    """
    Measure current and OS-tracked peak resident memory (RSS) in MiB using OS
    native calls (Windows ``GetProcessMemoryInfo``, psutil if present, or Unix
    ``resource.getrusage`` fallback).
    """
    rss_mb: Optional[float] = None
    peak_rss_mb: Optional[float] = None

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                rss_mb = round(counters.WorkingSetSize / (1024.0 * 1024.0), 3)
                peak_rss_mb = round(counters.PeakWorkingSetSize / (1024.0 * 1024.0), 3)
                return {"rss_mb": rss_mb, "peak_rss_mb": peak_rss_mb}
        except Exception:
            pass

    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()
        rss_mb = round(mem_info.rss / (1024.0 * 1024.0), 3)
        peak_val = getattr(mem_info, "peak_wset", None) or mem_info.rss
        peak_rss_mb = round(float(peak_val) / (1024.0 * 1024.0), 3)
        return {"rss_mb": rss_mb, "peak_rss_mb": peak_rss_mb}
    except Exception:
        pass

    try:
        import resource  # type: ignore

        getrusage_fn = getattr(resource, "getrusage", None)
        rusage_self = getattr(resource, "RUSAGE_SELF", None)
        if getrusage_fn is None or rusage_self is None:
            return {"rss_mb": None, "peak_rss_mb": None}
        usage = getrusage_fn(rusage_self)
        divisor = (1024.0 * 1024.0) if sys.platform == "darwin" else 1024.0
        val = round(float(usage.ru_maxrss) / divisor, 3)
        return {"rss_mb": val, "peak_rss_mb": val}
    except Exception:
        return {"rss_mb": None, "peak_rss_mb": None}


@contextmanager
def measure_memory_and_duration(enable_tracemalloc: bool = True) -> Generator[Dict[str, Any], None, None]:
    """
    Context manager recording elapsed wall-clock milliseconds, process RSS
    before/after, and Python heap peak allocation via ``tracemalloc`` when enabled.
    """
    stats: Dict[str, Any] = {
        "duration_ms": 0.0,
        "rss_before_mb": None,
        "rss_after_mb": None,
        "rss_delta_mb": None,
        "peak_rss_mb": None,
        "tracemalloc_peak_mb": None,
    }
    mem_before = get_process_memory_mb()
    stats["rss_before_mb"] = mem_before.get("rss_mb")

    started_trace = False
    if enable_tracemalloc:
        try:
            if not tracemalloc.is_tracing():
                tracemalloc.start()
                started_trace = True
            else:
                tracemalloc.reset_peak()
        except Exception:
            started_trace = False

    t0 = time.perf_counter()
    try:
        yield stats
    finally:
        stats["duration_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        if enable_tracemalloc:
            try:
                if tracemalloc.is_tracing():
                    _, peak_bytes = tracemalloc.get_traced_memory()
                    stats["tracemalloc_peak_mb"] = round(peak_bytes / (1024.0 * 1024.0), 3)
            except Exception:
                pass
            finally:
                if started_trace:
                    try:
                        tracemalloc.stop()
                    except Exception:
                        pass

        mem_after = get_process_memory_mb()
        stats["rss_after_mb"] = mem_after.get("rss_mb")
        stats["peak_rss_mb"] = mem_after.get("peak_rss_mb")
        if stats["rss_before_mb"] is not None and stats["rss_after_mb"] is not None:
            stats["rss_delta_mb"] = round(stats["rss_after_mb"] - stats["rss_before_mb"], 3)


class VisualExtractionMetrics:
    """Thread-safe observability aggregator for Visual Extraction runs."""

    def __init__(self, max_history: int = 100):
        self._lock = threading.RLock()
        self._history: Deque[Dict[str, Any]] = deque(maxlen=max(10, max_history))
        self._reset_counters_unlocked()

    def _reset_counters_unlocked(self) -> None:
        self._total_runs = 0
        self._failed_runs = 0
        self._partial_failure_runs = 0
        self._pages_processed = 0
        self._partial_failure_pages = 0
        self._full_page_renders = 0
        self._region_clip_renders = 0
        self._ocr_calls = 0
        self._durations_ms: Deque[float] = deque(maxlen=500)
        self._stage_totals_ms: Dict[str, float] = {}
        self._max_rss_mb: Optional[float] = None
        self._max_peak_rss_mb: Optional[float] = None
        self._max_tracemalloc_mb: Optional[float] = None

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._reset_counters_unlocked()

    def record_run(
        self,
        *,
        duration_ms: float,
        pages_processed: int = 0,
        full_page_renders: int = 0,
        region_clip_renders: int = 0,
        ocr_calls: int = 0,
        partial_failure_pages: int = 0,
        failed: bool = False,
        rss_before_mb: Optional[float] = None,
        rss_after_mb: Optional[float] = None,
        peak_rss_mb: Optional[float] = None,
        tracemalloc_peak_mb: Optional[float] = None,
        stage_timings_ms: Optional[Mapping[str, float]] = None,
        dpi: Optional[int] = None,
        workload_class: str = "visual",
        error_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = {
            "timestamp": time.time(),
            "workload_class": workload_class,
            "dpi": dpi,
            "duration_ms": round(duration_ms, 2),
            "pages_processed": max(0, pages_processed),
            "partial_failure_pages": max(0, partial_failure_pages),
            "failed": failed,
            "full_page_renders": max(0, full_page_renders),
            "region_clip_renders": max(0, region_clip_renders),
            "ocr_calls": max(0, ocr_calls),
            "rss_before_mb": rss_before_mb,
            "rss_after_mb": rss_after_mb,
            "peak_rss_mb": peak_rss_mb,
            "tracemalloc_peak_mb": tracemalloc_peak_mb,
            "stage_timings_ms": {
                k: round(v, 2)
                for k, v in (stage_timings_ms or {}).items()
            },
            "error_reason": error_reason[:240] if error_reason else None,
        }
        with self._lock:
            self._total_runs += 1
            if failed:
                self._failed_runs += 1
            if partial_failure_pages > 0:
                self._partial_failure_runs += 1
            self._pages_processed += entry["pages_processed"]
            self._partial_failure_pages += entry["partial_failure_pages"]
            self._full_page_renders += entry["full_page_renders"]
            self._region_clip_renders += entry["region_clip_renders"]
            self._ocr_calls += entry["ocr_calls"]
            self._durations_ms.append(entry["duration_ms"])

            for stage, dt in entry["stage_timings_ms"].items():
                self._stage_totals_ms[stage] = round(self._stage_totals_ms.get(stage, 0.0) + dt, 2)

            for val in (rss_before_mb, rss_after_mb):
                if val is not None and (self._max_rss_mb is None or val > self._max_rss_mb):
                    self._max_rss_mb = val
            if peak_rss_mb is not None and (self._max_peak_rss_mb is None or peak_rss_mb > self._max_peak_rss_mb):
                self._max_peak_rss_mb = peak_rss_mb
            if tracemalloc_peak_mb is not None and (
                self._max_tracemalloc_mb is None or tracemalloc_peak_mb > self._max_tracemalloc_mb
            ):
                self._max_tracemalloc_mb = tracemalloc_peak_mb

            self._history.append(entry)
        return entry

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            durs = sorted(self._durations_ms)
            total = self._total_runs
            avg_ms = round(sum(durs) / len(durs), 2) if durs else 0.0
            p95_idx = min(len(durs) - 1, max(0, round(0.95 * (len(durs) - 1)))) if durs else 0
            p95_ms = round(durs[p95_idx], 2) if durs else 0.0
            failure_rate = round(self._failed_runs / total, 4) if total > 0 else 0.0
            page_failure_rate = (
                round(self._partial_failure_pages / self._pages_processed, 4)
                if self._pages_processed > 0
                else 0.0
            )
            return {
                "total_runs": total,
                "failed_runs": self._failed_runs,
                "partial_failure_runs": self._partial_failure_runs,
                "failure_rate": failure_rate,
                "pages_processed": self._pages_processed,
                "partial_failure_pages": self._partial_failure_pages,
                "page_failure_rate": page_failure_rate,
                "avg_duration_ms": avg_ms,
                "min_duration_ms": round(durs[0], 2) if durs else 0.0,
                "max_duration_ms": round(durs[-1], 2) if durs else 0.0,
                "p95_duration_ms": p95_ms,
                "max_rss_mb": self._max_rss_mb,
                "max_peak_rss_mb": self._max_peak_rss_mb,
                "max_peak_tracemalloc_mb": self._max_tracemalloc_mb,
                "total_full_page_renders": self._full_page_renders,
                "total_region_clip_renders": self._region_clip_renders,
                "total_ocr_calls": self._ocr_calls,
                "stage_totals_ms": dict(self._stage_totals_ms),
                "recent_runs": list(self._history),
            }


GLOBAL_VISUAL_METRICS = VisualExtractionMetrics()
