import React, { useState, useEffect, useCallback } from 'react';
import {
  ClipboardList,
  X,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  Clock,
  Bell,
  CheckCircle2,
  XCircle,
  Timer,
  Filter,
  User,
  Phone,
  Stethoscope,
  Calendar,
  CalendarPlus,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useModal } from '../contexts/ModalContext';
import { useAuth } from '../contexts/AuthContext';
import { formatDate, formatTime } from '../lib/timezone';
import ThemedDateTimePicker from './ui/ThemedDateTimePicker';

const STATUS_CONFIG = {
  WAITING: {
    label: 'Waiting',
    icon: Clock,
    bg: 'bg-blue-50 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-400',
    border: 'border-blue-200 dark:border-blue-800',
    dot: 'bg-blue-500',
  },
  NOTIFIED: {
    label: 'Notified',
    icon: Bell,
    bg: 'bg-amber-50 dark:bg-amber-900/30',
    text: 'text-amber-700 dark:text-amber-400',
    border: 'border-amber-200 dark:border-amber-800',
    dot: 'bg-amber-500',
  },
  BOOKED: {
    label: 'Booked',
    icon: CheckCircle2,
    bg: 'bg-green-50 dark:bg-green-900/30',
    text: 'text-green-700 dark:text-green-400',
    border: 'border-green-200 dark:border-green-800',
    dot: 'bg-green-500',
  },
  EXPIRED: {
    label: 'Expired',
    icon: Timer,
    bg: 'bg-gray-50 dark:bg-gray-700/50',
    text: 'text-gray-500 dark:text-gray-400',
    border: 'border-gray-200 dark:border-gray-700',
    dot: 'bg-gray-400',
  },
  CANCELLED: {
    label: 'Cancelled',
    icon: XCircle,
    bg: 'bg-red-50 dark:bg-red-900/30',
    text: 'text-red-600 dark:text-red-400',
    border: 'border-red-200 dark:border-red-800',
    dot: 'bg-red-400',
  },
};

export default function WaitlistView() {
  const { user } = useAuth();
  const { confirm } = useModal();
  const tz = user?.timezone || 'America/Chicago';
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [promoteEntry, setPromoteEntry] = useState(null);
  const [promoteTime, setPromoteTime] = useState('');
  const [promoteSubmitting, setPromoteSubmitting] = useState(false);
  const [promoteError, setPromoteError] = useState(null);
  // Conflict-confirmation state: shown when the backend reports existing
  // appointments at the requested provider/slot.
  const [conflicts, setConflicts] = useState([]);
  const [conflictsChecking, setConflictsChecking] = useState(false);

  const fetchEntries = useCallback(async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      const url = `/api/waitlist${params.toString() ? '?' + params.toString() : ''}`;
      const data = await apiFetch(url);
      setEntries(data || []);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load waitlist');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filterStatus]);

  useEffect(() => {
    setLoading(true);
    fetchEntries();
  }, [fetchEntries]);

  async function handleCancel(entryId) {
    const ok = await confirm({
      title: 'Cancel Waitlist Entry?',
      message: 'The patient will be notified by SMS that their waitlist entry has been cancelled.',
      confirmText: 'Cancel Entry',
      variant: 'danger',
    });
    if (!ok) return;
    try {
      await apiFetch(`/api/waitlist/${entryId}`, { method: 'DELETE' });
      await fetchEntries();
    } catch (err) {
      setError(err.message || 'Failed to cancel entry');
    }
  }

  function openPromote(entry) {
    // Default the datetime-local input to the entry's preferred date +
    // time window start (or 09:00 if no time preference).
    const time = entry.preferred_time_start || '09:00';
    setPromoteTime(`${entry.preferred_date}T${time}`);
    setPromoteError(null);
    setPromoteEntry(entry);
  }

  function closePromote() {
    setPromoteEntry(null);
    setPromoteTime('');
    setPromoteError(null);
    setPromoteSubmitting(false);
    setConflicts([]);
    setConflictsChecking(false);
  }

  function isoFromLocal() {
    // datetime-local gives 'YYYY-MM-DDTHH:MM' — append :00 for ISO completeness.
    return promoteTime.length === 16 ? `${promoteTime}:00` : promoteTime;
  }

  // First step of the promote flow — check for conflicting appointments
  // before booking. If any are found, surface them in the confirmation
  // panel so the admin can decide to force-promote (doctor agrees) or back out.
  async function handlePromote() {
    if (!promoteEntry || !promoteTime) return;
    setPromoteSubmitting(true);
    setPromoteError(null);
    setConflicts([]);
    try {
      const iso = isoFromLocal();
      setConflictsChecking(true);
      const conflictRes = await apiFetch(
        `/api/waitlist/${promoteEntry.id}/check-conflicts`,
        { method: 'POST', body: JSON.stringify({ scheduled_at: iso }) },
      );
      setConflictsChecking(false);

      if (conflictRes?.conflicts?.length) {
        // Show conflicts, wait for admin to confirm force-promote
        setConflicts(conflictRes.conflicts);
        setPromoteSubmitting(false);
        return;
      }

      // No conflicts — go straight through the regular promote
      await apiFetch(`/api/waitlist/${promoteEntry.id}/promote`, {
        method: 'POST',
        body: JSON.stringify({ scheduled_at: iso, force: false }),
      });
      closePromote();
      await fetchEntries();
    } catch (err) {
      setPromoteError(err.message || 'Failed to promote entry');
    } finally {
      setPromoteSubmitting(false);
      setConflictsChecking(false);
    }
  }

  // Second step — admin has reviewed conflicts and chose to proceed anyway.
  // The doctor is ready, so we bypass the provider/time concurrency check.
  async function handleForcePromote() {
    if (!promoteEntry || !promoteTime) return;
    setPromoteSubmitting(true);
    setPromoteError(null);
    try {
      const iso = isoFromLocal();
      await apiFetch(`/api/waitlist/${promoteEntry.id}/promote`, {
        method: 'POST',
        body: JSON.stringify({ scheduled_at: iso, force: true }),
      });
      closePromote();
      await fetchEntries();
    } catch (err) {
      setPromoteError(err.message || 'Failed to promote entry');
    } finally {
      setPromoteSubmitting(false);
    }
  }

  // Group entries by status for stats
  const statusCounts = entries.reduce((acc, e) => {
    acc[e.status] = (acc[e.status] || 0) + 1;
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <ClipboardList className="w-7 h-7 text-primary-500" />
            Waitlist
          </h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Patients waiting for appointment openings. They're auto-notified when a cancellation
            matches their preferences.
          </p>
        </div>
        <button
          onClick={() => fetchEntries(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Status summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Object.entries(STATUS_CONFIG).map(([key, cfg]) => {
          const Icon = cfg.icon;
          const count = statusCounts[key] || 0;
          const isActive = filterStatus === key;
          return (
            <button
              key={key}
              onClick={() => setFilterStatus(isActive ? '' : key)}
              className={`rounded-xl border p-3 text-left transition-all ${
                isActive
                  ? `${cfg.bg} ${cfg.border} ring-2 ring-offset-1 ring-primary-300 dark:ring-offset-gray-900`
                  : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Icon className={`w-4 h-4 ${isActive ? cfg.text : 'text-gray-400'}`} />
                <span className={`text-xs font-medium ${isActive ? cfg.text : 'text-gray-500 dark:text-gray-400'}`}>
                  {cfg.label}
                </span>
              </div>
              <p className={`text-2xl font-bold mt-1 ${isActive ? cfg.text : 'text-gray-900 dark:text-white'}`}>
                {count}
              </p>
            </button>
          );
        })}
      </div>

      {/* Filter indicator */}
      {filterStatus && (
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          <Filter className="w-4 h-4" />
          Showing <strong>{filterStatus}</strong> entries
          <button
            onClick={() => setFilterStatus('')}
            className="ml-1 px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded-full text-xs hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            Clear
          </button>
        </div>
      )}

      {/* Entries list */}
      {entries.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
          <ClipboardList className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
            {filterStatus ? 'No matching entries' : 'Waitlist is empty'}
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {filterStatus
              ? `No entries with status "${filterStatus}". Try clearing the filter.`
              : 'When patients request a fully-booked slot, the AI agent will offer to add them here.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => {
            const cfg = STATUS_CONFIG[entry.status] || STATUS_CONFIG.WAITING;
            const StatusIcon = cfg.icon;
            return (
              <div
                key={entry.id}
                className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 hover:border-gray-300 dark:hover:border-gray-600 transition-colors"
              >
                <div className="flex items-start gap-4">
                  {/* Status indicator */}
                  <div
                    className={`w-10 h-10 rounded-full ${cfg.bg} flex items-center justify-center shrink-0`}
                  >
                    <StatusIcon className={`w-5 h-5 ${cfg.text}`} />
                  </div>

                  {/* Main content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-gray-900 dark:text-white">{entry.patient_name}</span>
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bg} ${cfg.text}`}
                      >
                        <div className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`}></div>
                        {cfg.label}
                      </span>
                    </div>

                    <div className="flex items-center gap-4 mt-1.5 text-sm text-gray-500 dark:text-gray-400 flex-wrap">
                      <span className="flex items-center gap-1">
                        <Phone className="w-3.5 h-3.5" />
                        {entry.patient_phone}
                      </span>
                      <span className="flex items-center gap-1">
                        <Stethoscope className="w-3.5 h-3.5" />
                        {entry.appointment_type}
                      </span>
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5" />
                        {entry.preferred_date}
                        {entry.preferred_time_start && (
                          <span className="text-gray-400">
                            {' '}
                            {entry.preferred_time_start}
                            {entry.preferred_time_end && `–${entry.preferred_time_end}`}
                          </span>
                        )}
                      </span>
                      {entry.provider_name && (
                        <span className="flex items-center gap-1">
                          <User className="w-3.5 h-3.5" />
                          {entry.provider_name}
                        </span>
                      )}
                    </div>

                    {/* Timeline details */}
                    <div className="flex items-center gap-4 mt-1 text-xs text-gray-400 dark:text-gray-500">
                      <span>Added {formatDate(entry.created_at, tz)}</span>
                      {entry.notified_at && (
                        <span>Notified {formatDate(entry.notified_at, tz)}</span>
                      )}
                      {entry.booked_at && (
                        <span className="text-green-600">
                          Booked {formatDate(entry.booked_at, tz)}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  {entry.status === 'WAITING' || entry.status === 'NOTIFIED' ? (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => openPromote(entry)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg hover:bg-green-100 dark:hover:bg-green-900/50 transition-colors"
                        title="Promote to a booked appointment"
                      >
                        <CalendarPlus className="w-4 h-4" />
                        Promote
                      </button>
                      <button
                        onClick={() => handleCancel(entry.id)}
                        className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors"
                        title="Cancel entry"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Promote modal */}
      {promoteEntry && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) closePromote();
          }}
        >
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md p-6">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
                  <CalendarPlus className="w-5 h-5 text-green-500" />
                  Promote to Appointment
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Book this patient into a real slot. They'll be notified by SMS.
                </p>
              </div>
              <button
                onClick={closePromote}
                className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-3 mb-4 text-sm space-y-1">
              <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300">
                <User className="w-3.5 h-3.5 text-gray-400" />
                <span className="font-medium">{promoteEntry.patient_name}</span>
              </div>
              <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                <Phone className="w-3.5 h-3.5" />
                {promoteEntry.patient_phone}
              </div>
              <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                <Stethoscope className="w-3.5 h-3.5" />
                {promoteEntry.appointment_type}
              </div>
              <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                <Calendar className="w-3.5 h-3.5" />
                Wanted {promoteEntry.preferred_date}
                {promoteEntry.preferred_time_start && (
                  <span>
                    {' '}
                    {promoteEntry.preferred_time_start}
                    {promoteEntry.preferred_time_end && `–${promoteEntry.preferred_time_end}`}
                  </span>
                )}
              </div>
            </div>

            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Scheduled date &amp; time
            </label>
            <ThemedDateTimePicker
              value={promoteTime}
              onChange={(v) => {
                setPromoteTime(v);
                // Any time change invalidates a previously-fetched conflict list
                if (conflicts.length) setConflicts([]);
              }}
              accent="primary"
              minuteStep={5}
              timezoneHint={`Interpreted in your office timezone (${tz}).`}
            />

            {/* Conflict panel — shown when the backend reports existing
                appointments at the chosen provider/slot. The admin can choose
                to proceed anyway (the doctor is ready) or back out. */}
            {conflicts.length > 0 && (
              <div className="mt-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                      {conflicts.length} existing appointment{conflicts.length === 1 ? '' : 's'} near this slot
                    </p>
                    <p className="text-xs text-amber-700 dark:text-amber-300 mt-0.5">
                      These appointments are already on the books for the same provider/window.
                      Promote anyway only if the doctor has agreed to take the overlap.
                    </p>
                  </div>
                </div>
                <ul className="mt-3 space-y-1.5 max-h-40 overflow-y-auto pr-1">
                  {conflicts.map((c) => (
                    <li
                      key={c.id}
                      className="bg-white dark:bg-gray-900/60 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-gray-900 dark:text-gray-100 truncate">
                          {c.patient_name}
                        </span>
                        <span className="text-gray-500 dark:text-gray-400 shrink-0">
                          {c.scheduled_at ? formatTime(c.scheduled_at, tz) : '—'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-gray-500 dark:text-gray-400">
                        <Stethoscope className="w-3 h-3" />
                        <span className="truncate">{c.appointment_type}</span>
                        {c.provider_name && (
                          <>
                            <span className="text-gray-300">·</span>
                            <User className="w-3 h-3" />
                            <span className="truncate">{c.provider_name}</span>
                          </>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {promoteError && (
              <div className="mt-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg p-3 text-sm text-red-700 dark:text-red-400">
                {promoteError}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 mt-5">
              <button
                onClick={closePromote}
                disabled={promoteSubmitting}
                className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              {conflicts.length > 0 ? (
                <button
                  onClick={handleForcePromote}
                  disabled={promoteSubmitting || !promoteTime}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-amber-600 hover:bg-amber-700 disabled:opacity-60 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {promoteSubmitting ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      Booking…
                    </>
                  ) : (
                    <>
                      <AlertTriangle className="w-4 h-4" />
                      Promote Anyway
                    </>
                  )}
                </button>
              ) : (
                <button
                  onClick={handlePromote}
                  disabled={promoteSubmitting || !promoteTime}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-60 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {promoteSubmitting || conflictsChecking ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      {conflictsChecking ? 'Checking…' : 'Booking…'}
                    </>
                  ) : (
                    <>
                      <CalendarPlus className="w-4 h-4" />
                      Confirm Booking
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
