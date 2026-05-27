import React, { useState, useEffect, useRef } from 'react';
import { Calendar, ChevronLeft, ChevronRight, X } from 'lucide-react';

/**
 * Themed calendar popover. Replaces native <input type="date">.
 *
 * Props:
 *   value         — selected Date object (or null)
 *   onChange      — (Date) => void
 *   onClear       — () => void  (optional; renders an "x" clear button)
 *   placeholder   — text when no value (default: "Pick a date")
 *   min           — minimum selectable Date (optional)
 *   max           — maximum selectable Date (optional)
 *   accent        — 'amber' | 'primary' (default 'amber')
 *   buttonClassName — extra classes for the trigger button
 *   formatLabel   — custom label formatter (Date) => string
 */
export default function ThemedDatePicker({
  value,
  onChange,
  onClear,
  placeholder = 'Pick a date',
  min,
  max,
  accent = 'amber',
  buttonClassName = '',
  formatLabel,
}) {
  const [open, setOpen] = useState(false);
  // Month being viewed in the popover (independent from selected value)
  const [viewMonth, setViewMonth] = useState(() => {
    const base = value || new Date();
    return new Date(base.getFullYear(), base.getMonth(), 1);
  });
  const ref = useRef(null);

  // Keep view month in sync when an external value is set
  useEffect(() => {
    if (value) {
      setViewMonth(new Date(value.getFullYear(), value.getMonth(), 1));
    }
  }, [value]);

  // Close on click outside / escape
  useEffect(() => {
    if (!open) return;
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const accentClasses = accent === 'amber'
    ? {
        button: value
          ? 'border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/50'
          : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600',
        selectedDay: 'bg-amber-500 text-white font-semibold hover:bg-amber-600',
        todayRing: 'ring-2 ring-amber-400',
      }
    : {
        button: value
          ? 'border-primary-200 dark:border-primary-700 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 hover:bg-primary-100 dark:hover:bg-primary-900/50'
          : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600',
        selectedDay: 'bg-primary-500 text-white font-semibold hover:bg-primary-600',
        todayRing: 'ring-2 ring-primary-400',
      };

  const displayLabel = value
    ? (formatLabel
        ? formatLabel(value)
        : value.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }))
    : placeholder;

  // ── Calendar grid construction ────────────────────────────────────────
  const monthStart = new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1);
  const monthEnd = new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 0);
  // Sunday-first grid leading from previous month
  const startWeekday = monthStart.getDay();
  const daysInMonth = monthEnd.getDate();

  const cells = [];
  // Leading blanks (previous month)
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(new Date(viewMonth.getFullYear(), viewMonth.getMonth(), d));
  }
  // Pad to multiple of 7
  while (cells.length % 7 !== 0) cells.push(null);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  function sameDay(a, b) {
    return a && b && a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function isDisabled(d) {
    if (!d) return true;
    if (min) {
      const minD = new Date(min); minD.setHours(0, 0, 0, 0);
      if (d < minD) return true;
    }
    if (max) {
      const maxD = new Date(max); maxD.setHours(0, 0, 0, 0);
      if (d > maxD) return true;
    }
    return false;
  }

  function gotoPrevMonth() {
    setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1));
  }
  function gotoNextMonth() {
    setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1));
  }
  function gotoToday() {
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    setViewMonth(new Date(t.getFullYear(), t.getMonth(), 1));
    onChange(t);
    setOpen(false);
  }
  function pickDay(d) {
    if (isDisabled(d)) return;
    onChange(d);
    setOpen(false);
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${accentClasses.button} ${buttonClassName}`}
      >
        <Calendar className="w-4 h-4 shrink-0" />
        <span>{displayLabel}</span>
        {value && onClear && (
          <X
            className="w-3.5 h-3.5 shrink-0 opacity-60 hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
          />
        )}
      </button>

      {open && (
        <div
          className="absolute z-40 mt-2 w-72 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl p-3"
        >
          {/* Header — month/year + nav */}
          <div className="flex items-center justify-between mb-2">
            <button
              type="button"
              onClick={gotoPrevMonth}
              className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
              aria-label="Previous month"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <p className="text-sm font-semibold text-gray-800 dark:text-gray-100">
              {viewMonth.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
            </p>
            <button
              type="button"
              onClick={gotoNextMonth}
              className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
              aria-label="Next month"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          {/* Weekday labels */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
              <div key={i} className="text-center text-[10px] font-medium text-gray-400 uppercase py-1">
                {d}
              </div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-1">
            {cells.map((d, idx) => {
              if (!d) return <div key={idx} />;
              const disabled = isDisabled(d);
              const isToday = sameDay(d, today);
              const isSelected = sameDay(d, value);
              const baseCls = 'h-9 w-full rounded-lg text-sm flex items-center justify-center transition-colors';
              let cls;
              if (isSelected) {
                cls = `${baseCls} ${accentClasses.selectedDay}`;
              } else if (isToday) {
                cls = `${baseCls} ${accentClasses.todayRing} text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700`;
              } else if (disabled) {
                cls = `${baseCls} text-gray-300 dark:text-gray-600 cursor-not-allowed`;
              } else {
                cls = `${baseCls} text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700`;
              }
              return (
                <button
                  key={idx}
                  type="button"
                  disabled={disabled}
                  onClick={() => pickDay(d)}
                  className={cls}
                >
                  {d.getDate()}
                </button>
              );
            })}
          </div>

          {/* Footer */}
          <div className="mt-3 flex items-center justify-between border-t border-gray-100 dark:border-gray-700 pt-2">
            <button
              type="button"
              onClick={gotoToday}
              className="text-xs font-medium text-primary-600 dark:text-primary-400 hover:underline"
            >
              Today
            </button>
            {value && onClear && (
              <button
                type="button"
                onClick={() => { onClear(); setOpen(false); }}
                className="text-xs font-medium text-gray-500 dark:text-gray-400 hover:underline"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
