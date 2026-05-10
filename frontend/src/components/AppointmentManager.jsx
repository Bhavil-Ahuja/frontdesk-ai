import React, { useState, useEffect } from 'react';
import {
  CalendarDays,
  CalendarCheck,
  Clock,
  User,
  Phone as PhoneIcon,
  Mail,
  X,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatDateTime, formatTime, isSameDay } from '../lib/timezone';

const STATUS_STYLES = {
  CONFIRMED: 'bg-green-100 text-green-700 border-green-200',
  CANCELLED: 'bg-red-100 text-red-700 border-red-200',
  RESCHEDULED: 'bg-blue-100 text-blue-700 border-blue-200',
  COMPLETED: 'bg-gray-100 text-gray-600 border-gray-200',
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

  useEffect(() => {
    fetchAppointments();
    // Auto-refresh every 60s so Cal.com bookings flow in live
    const interval = setInterval(fetchAppointments, 60000);
    return () => clearInterval(interval);
  }, []);

  async function fetchAppointments(forceSync = false) {
    setError(null);
    if (forceSync) setRefreshing(true);
    try {
      // ?sync=1 → backend pulls latest from Cal.com before returning
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
    if (!confirm('Are you sure you want to cancel this appointment?')) return;
    try {
      await apiFetch(`/api/appointments/${id}/cancel`, { method: 'POST' });
      setSelectedApt(null);
      fetchAppointments();
    } catch (err) {
      console.error('Cancel failed:', err);
      alert(err.message || 'Cancel failed');
    }
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
    return appointments.filter((a) => isSameDay(a.scheduled_at, date, tz));
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
          <h2 className="text-2xl font-bold text-gray-900">Appointments</h2>
          <p className="text-gray-500 mt-1">{appointments.length} total appointments</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleSyncGcal}
            disabled={syncing}
            title="Sync with Google Calendar"
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-primary-200 bg-primary-50 text-primary-700 hover:bg-primary-100 transition-colors disabled:opacity-50 text-sm font-medium"
          >
            <CalendarCheck className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing…' : 'Sync GCal'}
          </button>
          <button
            onClick={() => fetchAppointments(true)}
            disabled={refreshing}
            title="Refresh appointments"
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setWeekOffset((w) => w - 1)}
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => setWeekOffset(0)}
            className="px-3 py-2 text-sm font-medium text-primary-600 bg-primary-50 rounded-lg hover:bg-primary-100 transition-colors"
          >
            This Week
          </button>
          <button
            onClick={() => setWeekOffset((w) => w + 1)}
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {syncResult && (
        <div className="bg-primary-50 border border-primary-200 rounded-xl p-3 text-sm text-primary-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CalendarCheck className="w-4 h-4" />
            <span>
              <strong>Google Calendar synced</strong> — {syncResult.pulled} pulled, {syncResult.pushed} pushed
              {syncResult.cancelled > 0 && <>, {syncResult.cancelled} cancellations synced</>}
              {syncResult.errors > 0 && <span className="text-amber-600 ml-1">({syncResult.errors} errors)</span>}
            </span>
          </div>
          <button onClick={() => setSyncResult(null)} className="p-1 hover:bg-primary-100 rounded">
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Week label */}
      <p className="text-sm text-gray-500">
        {weekDays[0].toLocaleDateString('en-US', { month: 'long', day: 'numeric' })} —{' '}
        {weekDays[6].toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
      </p>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-4">
        {weekDays.map((day) => {
          const dayApts = getAppointmentsForDay(day);
          const isToday = day.toDateString() === today.toDateString();
          const isSunday = day.getDay() === 0;

          return (
            <div
              key={day.toISOString()}
              className={`bg-white rounded-xl border min-h-[200px] ${
                isToday ? 'border-primary-400 ring-1 ring-primary-200' : 'border-gray-200'
              } ${isSunday ? 'opacity-50' : ''}`}
            >
              {/* Day header */}
              <div className={`px-3 py-2 border-b text-center ${
                isToday ? 'bg-primary-50 border-primary-200' : 'bg-gray-50 border-gray-100'
              }`}>
                <p className="text-xs text-gray-500 uppercase">
                  {day.toLocaleDateString('en-US', { weekday: 'short' })}
                </p>
                <p className={`text-lg font-bold ${isToday ? 'text-primary-600' : 'text-gray-900'}`}>
                  {day.getDate()}
                </p>
              </div>

              {/* Appointments */}
              <div className="p-2 space-y-2">
                {isSunday ? (
                  <p className="text-xs text-gray-400 text-center py-2">Closed</p>
                ) : dayApts.length === 0 ? (
                  <p className="text-xs text-gray-300 text-center py-2">No appointments</p>
                ) : (
                  dayApts.map((apt) => (
                    <button
                      key={apt.id}
                      onClick={() => setSelectedApt(apt)}
                      className={`w-full text-left p-2 rounded-lg border-l-4 bg-gray-50 hover:bg-gray-100 transition-colors ${
                        TYPE_COLORS[apt.appointment_type] || 'border-l-gray-400'
                      }`}
                    >
                      <p className="text-xs font-semibold text-gray-800 truncate">
                        {apt.patient_name}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {formatTime(apt.scheduled_at, tz)}
                      </p>
                      <span
                        className={`inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          STATUS_STYLES[apt.status] || 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {apt.status}
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
        <div className="fixed inset-0 bg-black/30 z-50 flex justify-end">
          <div className="w-96 bg-white shadow-xl h-full overflow-y-auto">
            <div className="p-6 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-bold text-gray-900">Appointment Details</h3>
              <button
                onClick={() => setSelectedApt(null)}
                className="p-1 rounded-lg hover:bg-gray-100"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            <div className="p-6 space-y-5">
              <DetailRow icon={User} label="Patient" value={selectedApt.patient_name} />
              <DetailRow icon={PhoneIcon} label="Phone" value={selectedApt.patient_phone} />
              <DetailRow icon={Mail} label="Email" value={selectedApt.patient_email || '—'} />
              <DetailRow icon={CalendarDays} label="Type" value={selectedApt.appointment_type} />
              <DetailRow
                icon={Clock}
                label="Scheduled"
                value={formatDateTime(selectedApt.scheduled_at, tz)}
              />
              <DetailRow icon={Clock} label="Duration" value={`${selectedApt.duration_minutes} min`} />

              <div>
                <span
                  className={`inline-flex px-3 py-1.5 rounded-full text-xs font-medium ${
                    STATUS_STYLES[selectedApt.status] || 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {selectedApt.status}
                </span>
                <span className="ml-2 text-xs text-gray-400">
                  Booked via {selectedApt.booked_via}
                </span>
              </div>

              {selectedApt.notes && (
                <div className="p-3 bg-gray-50 rounded-lg">
                  <p className="text-xs font-medium text-gray-500 mb-1">Notes</p>
                  <p className="text-sm text-gray-700">{selectedApt.notes}</p>
                </div>
              )}

              {selectedApt.status === 'CONFIRMED' && (
                <button
                  onClick={() => handleCancel(selectedApt.id)}
                  className="w-full py-2.5 px-4 bg-red-50 text-red-600 border border-red-200 rounded-lg text-sm font-medium hover:bg-red-100 transition-colors"
                >
                  Cancel Appointment
                </button>
              )}
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
      <Icon className="w-4 h-4 text-gray-400 mt-0.5" />
      <div>
        <p className="text-xs text-gray-500">{label}</p>
        <p className="text-sm font-medium text-gray-900">{value}</p>
      </div>
    </div>
  );
}
