import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Users,
  Search,
  Phone,
  Mail,
  Calendar,
  Clock,
  AlertCircle,
  ChevronRight,
  ArrowLeft,
  Shield,
  Stethoscope,
  MessageSquare,
  PhoneCall,
  FileText,
  Star,
  Save,
  CheckCircle,
  User,
  ArrowUp,
  ArrowDown,
  Hash,
  RefreshCw,
  SortAsc,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatDateTime, formatDate, formatRelativeTime as fmtRelative } from '../lib/timezone';

// ── Status badge colors ────────────────────────────────────────────────────
const STATUS_COLORS = {
  CONFIRMED: { bg: 'bg-green-50', text: 'text-green-700', dot: 'bg-green-500' },
  COMPLETED: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500' },
  CANCELLED: { bg: 'bg-red-50', text: 'text-red-600', dot: 'bg-red-400' },
  RESCHEDULED: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-500' },
};

const OUTCOME_COLORS = {
  BOOKED: { bg: 'bg-green-50', text: 'text-green-700' },
  ESCALATED: { bg: 'bg-red-50', text: 'text-red-600' },
  INQUIRY: { bg: 'bg-blue-50', text: 'text-blue-700' },
  CANCELLED: { bg: 'bg-gray-50', text: 'text-gray-600' },
  ABANDONED: { bg: 'bg-gray-50', text: 'text-gray-400' },
};

export default function PatientCRM() {
  const { user } = useAuth();
  const tz = user?.timezone || 'America/Chicago';
  const [patients, setPatients] = useState([]);
  const [selectedPatientId, setSelectedPatientId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('recent');
  const searchTimeout = useRef(null);

  const fetchPatients = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('search', search.trim());
      params.set('sort', sort);
      const url = `/api/patients${params.toString() ? '?' + params.toString() : ''}`;
      const data = await apiFetch(url);
      setPatients(data || []);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load patients');
    } finally {
      setLoading(false);
    }
  }, [search, sort]);

  useEffect(() => {
    setLoading(true);
    // Debounce search
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => fetchPatients(), 300);
    return () => clearTimeout(searchTimeout.current);
  }, [fetchPatients]);

  if (selectedPatientId) {
    return (
      <PatientProfile
        patientId={selectedPatientId}
        tz={tz}
        onBack={() => {
          setSelectedPatientId(null);
          fetchPatients(); // Refresh list in case notes were updated
        }}
      />
    );
  }

  return (
    <div className="p-8 space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Users className="w-7 h-7 text-primary-500" />
          Patients
        </h2>
        <p className="text-gray-500 mt-1">
          Your patient database — built automatically from AI bookings, calls, and SMS conversations.
        </p>
      </div>

      {/* Search & Sort bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or phone..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20"
          />
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="px-3 py-2.5 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500 bg-white"
        >
          <option value="recent">Most Recent</option>
          <option value="name">Name A-Z</option>
          <option value="visits">Most Visits</option>
        </select>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
        </div>
      ) : patients.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Users className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            {search ? 'No patients match your search' : 'No patients yet'}
          </h3>
          <p className="text-sm text-gray-500">
            {search
              ? 'Try a different name or phone number.'
              : 'Patient records are created automatically when the AI books appointments.'}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {/* Table header */}
          <div className="grid grid-cols-12 gap-3 px-4 py-3 bg-gray-50 border-b border-gray-200 text-xs font-medium text-gray-500 uppercase tracking-wide">
            <div className="col-span-4">Patient</div>
            <div className="col-span-2">Contact</div>
            <div className="col-span-2 text-center">Visits</div>
            <div className="col-span-2">Last Seen</div>
            <div className="col-span-2 text-center">Upcoming</div>
          </div>

          {/* Rows */}
          {patients.map((p, idx) => (
            <button
              key={p.id}
              onClick={() => setSelectedPatientId(p.id)}
              className={`w-full grid grid-cols-12 gap-3 px-4 py-3.5 items-center text-left hover:bg-primary-50/50 transition-colors ${
                idx > 0 ? 'border-t border-gray-100' : ''
              }`}
            >
              {/* Name + type */}
              <div className="col-span-4 flex items-center gap-3 min-w-0">
                <div
                  className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${
                    p.is_new_patient
                      ? 'bg-amber-100 text-amber-700'
                      : 'bg-primary-100 text-primary-700'
                  }`}
                >
                  {(p.name || '?').charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">{p.name}</p>
                  <div className="flex items-center gap-1.5">
                    {p.is_new_patient && (
                      <span className="text-xs text-amber-600 font-medium">New</span>
                    )}
                    {p.preferred_appointment_type && (
                      <span className="text-xs text-gray-400 truncate">
                        {p.preferred_appointment_type.replace(/_/g, ' ')}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Contact */}
              <div className="col-span-2 text-xs text-gray-500 space-y-0.5 min-w-0">
                <p className="truncate">{p.phone}</p>
                {p.email && <p className="truncate text-gray-400">{p.email}</p>}
              </div>

              {/* Visit count */}
              <div className="col-span-2 text-center">
                <span className="text-sm font-semibold text-gray-900">{p.visit_count}</span>
                {p.no_show_count > 0 && (
                  <span className="ml-1 text-xs text-red-400">({p.no_show_count} NS)</span>
                )}
              </div>

              {/* Last seen */}
              <div className="col-span-2 text-xs text-gray-500">
                {p.last_appointment_at
                  ? fmtRelative(p.last_appointment_at, tz)
                  : <span className="text-gray-300">Never</span>}
              </div>

              {/* Upcoming */}
              <div className="col-span-2 flex items-center justify-center gap-1">
                {p.upcoming_count > 0 ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-50 text-green-700 rounded-full text-xs font-medium">
                    <Calendar className="w-3 h-3" />
                    {p.upcoming_count}
                  </span>
                ) : (
                  <span className="text-xs text-gray-300">—</span>
                )}
                <ChevronRight className="w-4 h-4 text-gray-300" />
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Patient count */}
      {!loading && patients.length > 0 && (
        <p className="text-xs text-gray-400 text-center">
          {patients.length} patient{patients.length !== 1 ? 's' : ''} total
        </p>
      )}
    </div>
  );
}


// ── Patient Profile (detail view) ──────────────────────────────────────────

function PatientProfile({ patientId, tz, onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('appointments');
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expandedCallId, setExpandedCallId] = useState(null);

  const fetchProfile = useCallback(async () => {
    try {
      const result = await apiFetch(`/api/patients/${patientId}`);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load patient');
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  async function handleSaveNotes() {
    setSaving(true);
    try {
      await apiFetch(`/api/patients/${patientId}`, {
        method: 'PUT',
        body: editForm,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      setEditing(false);
      await fetchProfile();
    } catch (err) {
      setError(err.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-8">
        <button onClick={onBack} className="flex items-center gap-2 text-gray-500 hover:text-gray-700 mb-4">
          <ArrowLeft className="w-4 h-4" /> Back to patients
        </button>
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500" />
          <p className="text-sm text-red-700">{error || 'Patient not found.'}</p>
        </div>
      </div>
    );
  }

  const p = data.patient;
  const appointments = data.appointments || [];
  const calls = data.calls || [];
  const smsMessages = data.sms_messages || [];

  const upcomingAppts = appointments.filter(
    (a) => a.status === 'CONFIRMED' && new Date(a.scheduled_at) > new Date()
  );
  const pastAppts = appointments.filter(
    (a) => a.status !== 'CONFIRMED' || new Date(a.scheduled_at) <= new Date()
  );

  const TABS = [
    { key: 'appointments', label: 'Appointments', icon: Calendar, count: appointments.length },
    { key: 'calls', label: 'Call Logs', icon: PhoneCall, count: calls.length },
    { key: 'sms', label: 'SMS', icon: MessageSquare, count: smsMessages.length },
  ];

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-2 text-gray-500 hover:text-gray-700 transition-colors text-sm"
      >
        <ArrowLeft className="w-4 h-4" /> All Patients
      </button>

      {saved && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-3 flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <span className="text-sm text-green-700">Patient updated.</span>
        </div>
      )}

      {/* Patient header card */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-start gap-4">
          {/* Avatar */}
          <div
            className={`w-14 h-14 rounded-full flex items-center justify-center text-xl font-bold shrink-0 ${
              p.is_new_patient
                ? 'bg-amber-100 text-amber-700'
                : 'bg-primary-100 text-primary-700'
            }`}
          >
            {(p.name || '?').charAt(0).toUpperCase()}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-bold text-gray-900">{p.name}</h2>
              {p.is_new_patient ? (
                <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full text-xs font-medium">
                  New Patient
                </span>
              ) : (
                <span className="px-2 py-0.5 bg-primary-50 text-primary-700 rounded-full text-xs font-medium">
                  Returning · {p.visit_count} visits
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 mt-2 text-sm text-gray-500 flex-wrap">
              <span className="flex items-center gap-1">
                <Phone className="w-3.5 h-3.5" /> {p.phone}
              </span>
              {p.email && (
                <span className="flex items-center gap-1">
                  <Mail className="w-3.5 h-3.5" /> {p.email}
                </span>
              )}
              {p.date_of_birth && (
                <span className="flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5" /> DOB: {p.date_of_birth}
                </span>
              )}
              {p.insurance_provider && (
                <span className="flex items-center gap-1">
                  <Shield className="w-3.5 h-3.5" /> {p.insurance_provider}
                </span>
              )}
            </div>

            {/* Quick stats */}
            <div className="flex items-center gap-4 mt-3">
              <StatBadge
                label="Total Visits"
                value={p.visit_count}
                icon={Hash}
              />
              <StatBadge
                label="Upcoming"
                value={upcomingAppts.length}
                icon={Calendar}
                color={upcomingAppts.length > 0 ? 'green' : 'gray'}
              />
              <StatBadge
                label="Calls"
                value={calls.length}
                icon={PhoneCall}
              />
              <StatBadge
                label="SMS"
                value={smsMessages.length}
                icon={MessageSquare}
              />
              {p.first_seen_at && (
                <StatBadge
                  label="Patient Since"
                  value={formatDate(p.first_seen_at, tz, { month: 'short', year: 'numeric', day: undefined })}
                  icon={Star}
                />
              )}
            </div>
          </div>

          {/* Edit button */}
          <button
            onClick={() => {
              setEditing(!editing);
              setEditForm({
                allergies: p.allergies || '',
                notes: p.notes || '',
                insurance_provider: p.insurance_provider || '',
              });
            }}
            className="px-3 py-2 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors shrink-0"
          >
            {editing ? 'Cancel' : 'Edit Notes'}
          </button>
        </div>

        {/* Edit form */}
        {editing && (
          <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Insurance</label>
                <input
                  type="text"
                  value={editForm.insurance_provider || ''}
                  onChange={(e) => setEditForm((f) => ({ ...f, insurance_provider: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500"
                  placeholder="Delta Dental, Aetna, etc."
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Allergies</label>
                <input
                  type="text"
                  value={editForm.allergies || ''}
                  onChange={(e) => setEditForm((f) => ({ ...f, allergies: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500"
                  placeholder="Latex, Penicillin, etc."
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Receptionist Notes</label>
              <textarea
                value={editForm.notes || ''}
                onChange={(e) => setEditForm((f) => ({ ...f, notes: e.target.value }))}
                rows={2}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500 resize-none"
                placeholder="Internal notes about this patient (visible to AI agent on next call)..."
              />
            </div>
            <button
              onClick={handleSaveNotes}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50 transition-colors"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        )}

        {/* Display allergies/notes if set and not editing */}
        {!editing && (p.allergies || p.notes) && (
          <div className="mt-4 pt-4 border-t border-gray-100 flex gap-6 text-sm">
            {p.allergies && (
              <div>
                <span className="text-xs font-medium text-red-500 uppercase tracking-wide">Allergies</span>
                <p className="text-gray-700 mt-0.5">{p.allergies}</p>
              </div>
            )}
            {p.notes && (
              <div>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Notes</span>
                <p className="text-gray-700 mt-0.5">{p.notes}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-gray-200">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-primary-500 text-primary-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
              <span
                className={`px-1.5 py-0.5 rounded-full text-xs ${
                  isActive ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-500'
                }`}
              >
                {tab.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === 'appointments' && (
        <AppointmentsTab upcoming={upcomingAppts} past={pastAppts} tz={tz} />
      )}
      {activeTab === 'calls' && (
        <CallsTab
          calls={calls}
          expandedCallId={expandedCallId}
          setExpandedCallId={setExpandedCallId}
          tz={tz}
        />
      )}
      {activeTab === 'sms' && <SMSTab messages={smsMessages} tz={tz} />}
    </div>
  );
}


// ── Sub-components ──────────────────────────────────────────────────────────

function StatBadge({ label, value, icon: Icon, color = 'gray' }) {
  const colors = {
    gray: 'bg-gray-50 text-gray-700',
    green: 'bg-green-50 text-green-700',
  };
  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg ${colors[color] || colors.gray}`}>
      <Icon className="w-3.5 h-3.5 opacity-50" />
      <span className="text-xs font-medium">{value}</span>
      <span className="text-xs text-gray-400">{label}</span>
    </div>
  );
}

function AppointmentsTab({ upcoming, past, tz }) {
  return (
    <div className="space-y-4">
      {upcoming.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
            <Calendar className="w-4 h-4 text-green-500" />
            Upcoming ({upcoming.length})
          </h4>
          <div className="space-y-2">
            {upcoming.map((a) => (
              <AppointmentRow key={a.id} appt={a} tz={tz} />
            ))}
          </div>
        </div>
      )}
      {past.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
            <Clock className="w-4 h-4 text-gray-400" />
            History ({past.length})
          </h4>
          <div className="space-y-2">
            {past.map((a) => (
              <AppointmentRow key={a.id} appt={a} tz={tz} />
            ))}
          </div>
        </div>
      )}
      {upcoming.length === 0 && past.length === 0 && (
        <EmptyState icon={Calendar} message="No appointment records." />
      )}
    </div>
  );
}

function AppointmentRow({ appt, tz }) {
  const status = STATUS_COLORS[appt.status] || STATUS_COLORS.CONFIRMED;
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 flex items-center gap-4">
      <div className={`w-2 h-2 rounded-full ${status.dot} shrink-0`}></div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-900">
            {appt.appointment_type?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
          </span>
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${status.bg} ${status.text}`}>
            {appt.status}
          </span>
          {appt.booked_via === 'AI' && (
            <span className="px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded text-xs font-medium">
              AI Booked
            </span>
          )}
          {appt.confirmed_by_patient === true && (
            <span className="px-1.5 py-0.5 bg-green-50 text-green-600 rounded text-xs font-medium">
              ✓ Confirmed
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-0.5">
          {appt.scheduled_at ? formatDateTime(appt.scheduled_at, tz) : ''}{' '}
          · {appt.duration_minutes} min
        </p>
      </div>
    </div>
  );
}

function CallsTab({ calls, expandedCallId, setExpandedCallId, tz }) {
  if (calls.length === 0) {
    return <EmptyState icon={PhoneCall} message="No call records." />;
  }
  return (
    <div className="space-y-2">
      {calls.map((c) => {
        const isExpanded = expandedCallId === c.id;
        const outcome = OUTCOME_COLORS[c.outcome] || OUTCOME_COLORS.INQUIRY;
        return (
          <div key={c.id} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <button
              onClick={() => setExpandedCallId(isExpanded ? null : c.id)}
              className="w-full flex items-center gap-4 p-3 text-left hover:bg-gray-50 transition-colors"
            >
              <PhoneCall className="w-4 h-4 text-gray-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900">
                    {c.started_at
                      ? formatDateTime(c.started_at, tz, { weekday: undefined, year: undefined })
                      : 'Unknown'}
                  </span>
                  {c.outcome && (
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs font-medium ${outcome.bg} ${outcome.text}`}
                    >
                      {c.outcome}
                    </span>
                  )}
                  {c.duration_seconds != null && (
                    <span className="text-xs text-gray-400">
                      {Math.floor(c.duration_seconds / 60)}:{String(c.duration_seconds % 60).padStart(2, '0')}
                    </span>
                  )}
                </div>
                {c.summary && (
                  <p className="text-xs text-gray-500 mt-0.5 truncate">{c.summary}</p>
                )}
              </div>
              <ChevronRight
                className={`w-4 h-4 text-gray-300 transition-transform ${
                  isExpanded ? 'rotate-90' : ''
                }`}
              />
            </button>

            {/* Transcript */}
            {isExpanded && c.transcript && c.transcript.length > 0 && (
              <div className="border-t border-gray-100 max-h-80 overflow-y-auto p-3 bg-gray-50 space-y-2">
                {c.transcript.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex ${
                      msg.role === 'assistant' ? 'justify-end' : 'justify-start'
                    }`}
                  >
                    <div
                      className={`max-w-[75%] rounded-xl px-3 py-2 text-xs ${
                        msg.role === 'assistant'
                          ? 'bg-primary-500 text-white rounded-br-sm'
                          : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                      }`}
                    >
                      <p className={`text-[10px] mb-0.5 ${
                        msg.role === 'assistant' ? 'text-primary-100' : 'text-gray-400'
                      }`}>
                        {msg.role === 'assistant' ? 'AI Agent' : 'Patient'}
                      </p>
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SMSTab({ messages, tz }) {
  if (messages.length === 0) {
    return <EmptyState icon={MessageSquare} message="No SMS messages." />;
  }
  return (
    <div className="bg-white rounded-xl border border-gray-200 max-h-[500px] overflow-y-auto p-4 space-y-2">
      {/* Messages are newest first from API, reverse for chat order */}
      {[...messages].reverse().map((msg) => {
        const isOutbound = msg.direction === 'OUTBOUND';
        return (
          <div key={msg.id} className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[70%] rounded-2xl px-3 py-2 ${
                isOutbound
                  ? 'bg-primary-500 text-white rounded-br-md'
                  : 'bg-gray-100 text-gray-900 rounded-bl-md'
              }`}
            >
              <div className={`flex items-center gap-1 mb-0.5 text-[10px] ${
                isOutbound ? 'text-primary-100' : 'text-gray-400'
              }`}>
                {isOutbound ? (
                  <><ArrowUp className="w-2.5 h-2.5" /> AI</>
                ) : (
                  <><ArrowDown className="w-2.5 h-2.5" /> Patient</>
                )}
              </div>
              <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>
              <p className={`text-[10px] mt-1 ${isOutbound ? 'text-primary-200' : 'text-gray-400'}`}>
                {msg.created_at ? formatDateTime(msg.created_at, tz) : ''}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EmptyState({ icon: Icon, message }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
      <Icon className="w-10 h-10 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );
}


// ── Helpers ─────────────────────────────────────────────────────────────────
// formatRelativeTime is now imported from lib/timezone.js as fmtRelative
