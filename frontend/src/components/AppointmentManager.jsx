import React, { useState, useEffect, useRef } from 'react';
import {
  CalendarDays,
  CalendarCheck,
  Clock,
  User,
  UserCog,
  Users,
  Phone as PhoneIcon,
  Mail,
  X,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  CheckCircle2,
  XCircle,
  FileText,
  Save,
  Check,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatDateTime, formatTime, isSameDay } from '../lib/timezone';
import ThemedDatePicker from './ui/ThemedDatePicker';

const STATUS_STYLES = {
  CONFIRMED: 'bg-green-100 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800',
  CANCELLED: 'bg-red-100 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800',
  RESCHEDULED: 'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800',
  COMPLETED: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800',
  NO_SHOW: 'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800',
};

const STATUS_LABELS = {
  CONFIRMED: 'Confirmed',
  CANCELLED: 'Cancelled',
  RESCHEDULED: 'Rescheduled',
  COMPLETED: 'Attended',
  NO_SHOW: 'No Show',
};

const TYPE_COLORS = {
  'Routine Cleaning': 'border-l-green-400',
  'New Patient Exam + Cleaning': 'border-l-blue-400',
  'Emergency': 'border-l-red-400',
  'Consultation': 'border-l-purple-400',
  'Filling': 'border-l-amber-400',
  'Crown Preparation': 'border-l-pink-400',
  'Teeth Whitening': 'border-l-cyan-400',
};

export default function AppointmentManager() {
  const { user } = useAuth();
  const tz = user?.timezone || 'America/Chicago';
  const [appointments, setAppointments] = useState([]);
  const [selectedApt, setSelectedApt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [weekOffset, setWeekOffset] = useState(0);
  const [error, setError] = useState(null);
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  // When set, the grid highlights this exact day inside the visible week.
  // Used by the calendar date picker so admins can jump to a date and have
  // it stand out in the week grid.
  const [highlightedDate, setHighlightedDate] = useState(null);

  // Notes editing state
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesText, setNotesText] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);

  // Status update state
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null); // { action: 'attended'|'no-show'|'cancel', id: number }

  useEffect(() => {
    fetchAppointments();
    fetchProviders();
    // Auto-refresh every 60s so new bookings flow in live
    const interval = setInterval(fetchAppointments, 60000);
    return () => clearInterval(interval);
  }, []);

  async function fetchProviders() {
    try {
      const data = await apiFetch('/api/providers');
      setProviders(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to fetch providers:', err);
    }
  }

  async function fetchAppointments(forceSync = false) {
    setError(null);
    if (forceSync) setRefreshing(true);
    try {
      // ?sync=1 -> backend pulls latest from Google Calendar before returning
      const path = forceSync ? '/api/appointments?sync=1' : '/api/appointments';
      const data = await apiFetch(path);
      setAppointments(Array.isArray(data) ? data : data.items || []);
    } catch (err) {
      console.error('Failed to fetch appointments:', err);
      setError(err.message || 'Failed to load appointments');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function handleSyncGcal() {
    setError(null);
    setSyncResult(null);
    setSyncing(true);
    try {
      const data = await apiFetch('/api/appointments/sync-gcal', { method: 'POST' });
      setSyncResult(data);
      // Refresh the list after sync
      await fetchAppointments();
      // Auto-dismiss the success banner after 8 seconds
      setTimeout(() => setSyncResult(null), 8000);
    } catch (err) {
      console.error('Google Calendar sync failed:', err);
      setError(err.message || 'Google Calendar sync failed');
    } finally {
      setSyncing(false);
    }
  }

  async function handleCancel(id) {
    setUpdatingStatus(true);
    try {
      await apiFetch(`/api/appointments/${id}/cancel`, { method: 'POST' });
      setSelectedApt(null);
      setConfirmAction(null);
      fetchAppointments();
    } catch (err) {
      console.error('Cancel failed:', err);
      alert(err.message || 'Cancel failed');
    } finally {
      setUpdatingStatus(false);
    }
  }

  async function handleStatusUpdate(id, newStatus) {
    setUpdatingStatus(true);
    try {
      const result = await apiFetch(`/api/appointments/${id}`, {
        method: 'PATCH',
        body: { status: newStatus },
      });
      // Update the selected appointment in-place
      setSelectedApt((prev) => prev ? { ...prev, status: result.current_status, notes: result.notes } : null);
      setConfirmAction(null);
      fetchAppointments();
    } catch (err) {
      console.error('Status update failed:', err);
      alert(err.message || 'Status update failed');
    } finally {
      setUpdatingStatus(false);
    }
  }

  async function handleSaveNotes(id) {
    setSavingNotes(true);
    try {
      const result = await apiFetch(`/api/appointments/${id}`, {
        method: 'PATCH',
        body: { notes: notesText },
      });
      setSelectedApt((prev) => prev ? { ...prev, notes: result.notes } : null);
      setEditingNotes(false);
      fetchAppointments();
    } catch (err) {
      console.error('Save notes failed:', err);
      alert(err.message || 'Failed to save notes');
    } finally {
      setSavingNotes(false);
    }
  }

  // Compute the Monday of any given date (ISO week start).
  function mondayOf(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    const dayIdx = d.getDay(); // 0 = Sun
    const diff = dayIdx === 0 ? -6 : 1 - dayIdx;
    d.setDate(d.getDate() + diff);
    return d;
  }

  // Jump to a specific date — set weekOffset so the date appears in the week
  // grid and highlight it. Used by the calendar date picker.
  function jumpToDate(date) {
    if (!date) return;
    const target = new Date(date);
    target.setHours(0, 0, 0, 0);
    const targetMonday = mondayOf(target);
    const todayMonday = mondayOf(new Date());
    const diffMs = targetMonday - todayMonday;
    const diffWeeks = Math.round(diffMs / (7 * 24 * 60 * 60 * 1000));
    setWeekOffset(diffWeeks);
    setHighlightedDate(target);
  }

  // Build a week grid
  const today = new Date();
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay() + 1 + weekOffset * 7); // Monday

  const weekDays = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    return d;
  });

  function getAppointmentsForDay(date) {
    return appointments.filter((a) => {
      if (!isSameDay(a.scheduled_at, date, tz)) return false;
      if (selectedProvider && a.provider_id !== selectedProvider) return false;
      return true;
    });
  }

  // Check if an appointment is in the past (for showing status actions)
  function isPastAppointment(apt) {
    return new Date(apt.scheduled_at) < new Date();
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Appointments</h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1">{appointments.length} total appointments</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Polished provider dropdown — replaces the basic <select> */}
          <ProviderPicker
            providers={providers}
            value={selectedProvider}
            onChange={setSelectedProvider}
          />

          {/* Date picker — jump to any date's week */}
          <ThemedDatePicker
            value={highlightedDate}
            onChange={jumpToDate}
            onClear={() => setHighlightedDate(null)}
            accent="amber"
            placeholder="Pick a date"
          />

          <button
            onClick={handleSyncGcal}
            disabled={syncing}
            title="Sync with Google Calendar"
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-primary-200 dark:border-primary-700 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 hover:bg-primary-100 dark:hover:bg-primary-900/50 transition-colors disabled:opacity-50 text-sm font-medium"
          >
            <CalendarCheck className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing...' : 'Sync GCal'}
          </button>
          <button
            onClick={() => fetchAppointments(true)}
            disabled={refreshing}
            title="Refresh appointments"
            className="p-2 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 text-gray-600 dark:text-gray-400 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setWeekOffset((w) => w - 1)}
            className="p-2 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <ChevronLeft className="w-4 h-4 text-gray-600 dark:text-gray-400" />
          </button>
          <button
            onClick={() => { setWeekOffset(0); setHighlightedDate(null); }}
            className="px-3 py-2 text-sm font-medium text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/30 rounded-lg hover:bg-primary-100 dark:hover:bg-primary-900/50 transition-colors"
          >
            This Week
          </button>
          <button
            onClick={() => setWeekOffset((w) => w + 1)}
            className="p-2 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <ChevronRight className="w-4 h-4 text-gray-600 dark:text-gray-400" />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-3 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {syncResult && (
        <div className="bg-primary-50 dark:bg-primary-900/30 border border-primary-200 dark:border-primary-800 rounded-xl p-3 text-sm text-primary-700 dark:text-primary-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CalendarCheck className="w-4 h-4" />
            <span>
              <strong>Google Calendar synced</strong> — {syncResult.pulled} pulled, {syncResult.pushed} pushed
              {syncResult.cancelled > 0 && <>, {syncResult.cancelled} cancellations synced</>}
              {syncResult.errors > 0 && <span className="text-amber-600 dark:text-amber-400 ml-1">({syncResult.errors} errors)</span>}
            </span>
          </div>
          <button onClick={() => setSyncResult(null)} className="p-1 hover:bg-primary-100 dark:hover:bg-primary-800 rounded">
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Week label */}
      <p className="text-sm text-gray-500 dark:text-gray-400">
        {weekDays[0].toLocaleDateString('en-US', { month: 'long', day: 'numeric' })} —{' '}
        {weekDays[6].toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
      </p>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-4">
        {weekDays.map((day) => {
          const dayApts = getAppointmentsForDay(day);
          const isToday = day.toDateString() === today.toDateString();
          const isHighlighted =
            highlightedDate && day.toDateString() === highlightedDate.toDateString();
          const isSunday = day.getDay() === 0;
          const isPast = day < today && !isToday;

          // Border / ring resolution: highlighted picked-date wins over today.
          let borderRing =
            'border-gray-200 dark:border-gray-700';
          if (isHighlighted) {
            borderRing =
              'border-amber-400 dark:border-amber-500 ring-2 ring-amber-300 dark:ring-amber-700';
          } else if (isToday) {
            borderRing =
              'border-primary-400 dark:border-primary-500 ring-1 ring-primary-200 dark:ring-primary-800';
          }

          return (
            <div
              key={day.toISOString()}
              className={`bg-white dark:bg-gray-800 rounded-xl border min-h-[200px] ${borderRing} ${isSunday ? 'opacity-50' : ''} ${isPast ? 'opacity-80' : ''}`}
            >
              {/* Day header */}
              <div className={`px-3 py-2 border-b text-center ${
                isHighlighted
                  ? 'bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800'
                  : isToday
                  ? 'bg-primary-50 dark:bg-primary-900/30 border-primary-200 dark:border-primary-800'
                  : 'bg-gray-50 dark:bg-gray-700/50 border-gray-100 dark:border-gray-700'
              }`}>
                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase">
                  {day.toLocaleDateString('en-US', { weekday: 'short' })}
                </p>
                <p className={`text-lg font-bold ${
                  isHighlighted
                    ? 'text-amber-600 dark:text-amber-400'
                    : isToday
                    ? 'text-primary-600 dark:text-primary-400'
                    : 'text-gray-900 dark:text-white'
                }`}>
                  {day.getDate()}
                </p>
              </div>

              {/* Appointments */}
              <div className="p-2 space-y-2">
                {isSunday ? (
                  <p className="text-xs text-gray-400 dark:text-gray-500 text-center py-2">Closed</p>
                ) : dayApts.length === 0 ? (
                  <p className="text-xs text-gray-300 dark:text-gray-600 text-center py-2">No appointments</p>
                ) : (
                  dayApts.map((apt) => (
                    <button
                      key={apt.id}
                      onClick={() => {
                        setSelectedApt(apt);
                        setEditingNotes(false);
                        setNotesText(apt.notes || '');
                      }}
                      className={`w-full text-left p-2 rounded-lg border-l-4 bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors ${
                        TYPE_COLORS[apt.appointment_type] || 'border-l-gray-400'
                      }`}
                    >
                      <p className="text-xs font-semibold text-gray-800 dark:text-gray-200 truncate">
                        {apt.patient_name}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        {formatTime(apt.scheduled_at, tz)}
                        {apt.provider_name && <span className="ml-1">• {apt.provider_name}</span>}
                      </p>
                      <span
                        className={`inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          STATUS_STYLES[apt.status] || 'bg-gray-100 text-gray-600 dark:bg-gray-600 dark:text-gray-300'
                        }`}
                      >
                        {STATUS_LABELS[apt.status] || apt.status}
                      </span>
                    </button>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Detail drawer */}
      {selectedApt && (
        <div className="fixed inset-0 bg-black/30 z-50 flex justify-end" onClick={() => setSelectedApt(null)}>
          <div className="w-[420px] bg-white dark:bg-gray-800 shadow-xl h-full overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">Appointment Details</h3>
              <button
                onClick={() => setSelectedApt(null)}
                className="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                <X className="w-5 h-5 text-gray-500 dark:text-gray-400" />
              </button>
            </div>
            <div className="p-6 space-y-5">
              <DetailRow icon={User} label="Patient" value={selectedApt.patient_name} />
              <DetailRow icon={PhoneIcon} label="Phone" value={selectedApt.patient_phone} />
              <DetailRow icon={Mail} label="Email" value={selectedApt.patient_email || '—'} />
              <DetailRow icon={CalendarDays} label="Type" value={selectedApt.appointment_type} />
              <DetailRow icon={UserCog} label="Doctor" value={selectedApt.provider_name || '—'} />
              <DetailRow
                icon={Clock}
                label="Scheduled"
                value={formatDateTime(selectedApt.scheduled_at, tz)}
              />
              <DetailRow icon={Clock} label="Duration" value={`${selectedApt.duration_minutes} min`} />

              <div>
                <span
                  className={`inline-flex px-3 py-1.5 rounded-full text-xs font-medium ${
                    STATUS_STYLES[selectedApt.status] || 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
                  }`}
                >
                  {STATUS_LABELS[selectedApt.status] || selectedApt.status}
                </span>
                <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">
                  Booked via {selectedApt.booked_via}
                </span>
              </div>

              {/* Notes section — editable */}
              <div className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400 flex items-center gap-1">
                    <FileText className="w-3 h-3" />
                    Visit Notes
                  </p>
                  {!editingNotes && (
                    <button
                      onClick={() => {
                        setNotesText(selectedApt.notes || '');
                        setEditingNotes(true);
                      }}
                      className="text-xs text-primary-600 dark:text-primary-400 hover:underline"
                    >
                      {selectedApt.notes ? 'Edit' : 'Add Notes'}
                    </button>
                  )}
                </div>
                {editingNotes ? (
                  <div className="space-y-2">
                    <textarea
                      value={notesText}
                      onChange={(e) => setNotesText(e.target.value)}
                      rows={4}
                      className="w-full p-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-300 focus:border-primary-300 resize-none"
                      placeholder="Add notes about this visit (visible to AI on next call)..."
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleSaveNotes(selectedApt.id)}
                        disabled={savingNotes}
                        className="flex items-center gap-1 px-3 py-1.5 bg-primary-600 text-white rounded-lg text-xs font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
                      >
                        <Save className="w-3 h-3" />
                        {savingNotes ? 'Saving...' : 'Save'}
                      </button>
                      <button
                        onClick={() => setEditingNotes(false)}
                        className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-600 rounded-lg transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-gray-700 dark:text-gray-300">
                    {selectedApt.notes || <span className="text-gray-400 dark:text-gray-500 italic">No notes yet</span>}
                  </p>
                )}
              </div>

              {/* Action buttons — context-sensitive */}
              <div className="space-y-2 pt-2 border-t border-gray-100 dark:border-gray-700">
                {/* Past CONFIRMED → mark attended or no-show */}
                {isPastAppointment(selectedApt) && selectedApt.status === 'CONFIRMED' && (
                  <>
                    <p className="text-xs text-amber-600 dark:text-amber-400 font-medium mb-2">
                      This appointment is in the past. Please update the outcome:
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setConfirmAction({ action: 'attended', id: selectedApt.id, status: 'COMPLETED' })}
                        disabled={updatingStatus}
                        className="flex-1 flex items-center justify-center gap-1.5 py-2.5 px-4 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 rounded-lg text-sm font-medium hover:bg-emerald-100 dark:hover:bg-emerald-900/50 disabled:opacity-50 transition-colors"
                      >
                        <CheckCircle2 className="w-4 h-4" />
                        Attended
                      </button>
                      <button
                        onClick={() => setConfirmAction({ action: 'no-show', id: selectedApt.id, status: 'NO_SHOW' })}
                        disabled={updatingStatus}
                        className="flex-1 flex items-center justify-center gap-1.5 py-2.5 px-4 bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 rounded-lg text-sm font-medium hover:bg-amber-100 dark:hover:bg-amber-900/50 disabled:opacity-50 transition-colors"
                      >
                        <XCircle className="w-4 h-4" />
                        No Show
                      </button>
                    </div>
                  </>
                )}

                {/* Correction: NO_SHOW → mark as actually attended */}
                {selectedApt.status === 'NO_SHOW' && (
                  <button
                    onClick={() => setConfirmAction({ action: 'correct-attended', id: selectedApt.id, status: 'COMPLETED' })}
                    disabled={updatingStatus}
                    className="w-full flex items-center justify-center gap-1.5 py-2.5 px-4 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 rounded-lg text-sm font-medium hover:bg-emerald-100 dark:hover:bg-emerald-900/50 disabled:opacity-50 transition-colors"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    Correct to Attended
                  </button>
                )}

                {/* Correction: COMPLETED → mark as actually no-show */}
                {selectedApt.status === 'COMPLETED' && (
                  <button
                    onClick={() => setConfirmAction({ action: 'correct-no-show', id: selectedApt.id, status: 'NO_SHOW' })}
                    disabled={updatingStatus}
                    className="w-full flex items-center justify-center gap-1.5 py-2.5 px-4 bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 rounded-lg text-sm font-medium hover:bg-amber-100 dark:hover:bg-amber-900/50 disabled:opacity-50 transition-colors"
                  >
                    <XCircle className="w-4 h-4" />
                    Correct to No Show
                  </button>
                )}

                {/* Future CONFIRMED → cancel */}
                {selectedApt.status === 'CONFIRMED' && !isPastAppointment(selectedApt) && (
                  <button
                    onClick={() => setConfirmAction({ action: 'cancel', id: selectedApt.id })}
                    className="w-full py-2.5 px-4 bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded-lg text-sm font-medium hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors"
                  >
                    Cancel Appointment
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation modal */}
      {confirmAction && (
        <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4" onClick={() => setConfirmAction(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">
              {confirmAction.action === 'cancel' ? 'Cancel Appointment?' : 'Update Status?'}
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {confirmAction.action === 'attended' && 'Mark this appointment as attended?'}
              {confirmAction.action === 'no-show' && 'Mark this appointment as no-show?'}
              {confirmAction.action === 'correct-attended' && 'Change status from No Show to Attended?'}
              {confirmAction.action === 'correct-no-show' && 'Change status from Attended to No Show?'}
              {confirmAction.action === 'cancel' && 'Are you sure you want to cancel this appointment?'}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmAction(null)}
                disabled={updatingStatus}
                className="flex-1 px-4 py-2.5 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (confirmAction.action === 'cancel') {
                    handleCancel(confirmAction.id);
                  } else {
                    handleStatusUpdate(confirmAction.id, confirmAction.status);
                  }
                }}
                disabled={updatingStatus}
                className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors ${
                  confirmAction.action === 'cancel'
                    ? 'bg-red-500 text-white hover:bg-red-600'
                    : confirmAction.status === 'COMPLETED'
                    ? 'bg-emerald-500 text-white hover:bg-emerald-600'
                    : 'bg-amber-500 text-white hover:bg-amber-600'
                }`}
              >
                {updatingStatus ? 'Updating...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DetailRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3">
      <Icon className="w-4 h-4 text-gray-400 dark:text-gray-500 mt-0.5" />
      <div>
        <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
        <p className="text-sm font-medium text-gray-900 dark:text-white">{value}</p>
      </div>
    </div>
  );
}

// ── Polished provider picker (replaces the native <select>) ────────────────
function ProviderPicker({ providers, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = providers.find((p) => p.id === value);

  // Close on outside click / Escape
  useEffect(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false);
    }
    if (open) {
      document.addEventListener('mousedown', onDoc);
      document.addEventListener('keydown', onKey);
    }
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 pl-3 pr-2 py-2 rounded-lg border text-sm font-medium transition-colors min-w-[180px] ${
          selected
            ? 'border-primary-200 dark:border-primary-700 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 hover:bg-primary-100 dark:hover:bg-primary-900/50'
            : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600'
        }`}
      >
        <Users className="w-4 h-4 shrink-0" />
        <span className="flex-1 text-left truncate">
          {selected ? selected.name : 'All Doctors'}
        </span>
        <ChevronDown
          className={`w-4 h-4 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-64 max-h-80 overflow-y-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-xl z-30 py-1">
          <button
            type="button"
            onClick={() => { onChange(null); setOpen(false); }}
            className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${
              !value ? 'text-primary-700 dark:text-primary-300 font-medium' : 'text-gray-700 dark:text-gray-300'
            }`}
          >
            <Users className="w-4 h-4 text-gray-400 shrink-0" />
            <span className="flex-1">All Doctors</span>
            {!value && <Check className="w-4 h-4 text-primary-500 shrink-0" />}
          </button>
          {providers.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-400 dark:text-gray-500 italic">
              No doctors configured yet.
            </p>
          ) : (
            providers.map((p) => {
              const isSelected = p.id === value;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => { onChange(p.id); setOpen(false); }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${
                    isSelected ? 'text-primary-700 dark:text-primary-300 font-medium' : 'text-gray-700 dark:text-gray-300'
                  }`}
                >
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary-100 to-primary-200 dark:from-primary-900/50 dark:to-primary-800/50 flex items-center justify-center shrink-0">
                    <span className="text-xs font-semibold text-primary-700 dark:text-primary-300">
                      {(p.name || '?').charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="truncate">{p.name}</p>
                    {p.specialty && (
                      <p className="text-[11px] text-gray-400 dark:text-gray-500 truncate">{p.specialty}</p>
                    )}
                  </div>
                  {isSelected && <Check className="w-4 h-4 text-primary-500 shrink-0" />}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

