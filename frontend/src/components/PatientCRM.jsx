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
  Stethoscope,
  MessageSquare,
  FileText,
  Star,
  Save,
  CheckCircle,
  CheckCircle2,
  XCircle,
  User,
  ArrowUp,
  ArrowDown,
  Hash,
  RefreshCw,
  SortAsc,
  Trash2,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { useModal } from '../contexts/ModalContext';
import { formatDateTime, formatDate, formatRelativeTime as fmtRelative } from '../lib/timezone';
import ThemedSelect from './ui/ThemedSelect';
import TestDataToggle, { TestBadge } from './ui/TestDataToggle';

// ── Status badge colors ────────────────────────────────────────────────────
const STATUS_COLORS = {
  CONFIRMED: { bg: 'bg-green-50 dark:bg-green-900/30', text: 'text-green-700 dark:text-green-400', dot: 'bg-green-500' },
  COMPLETED: { bg: 'bg-blue-50 dark:bg-blue-900/30', text: 'text-blue-700 dark:text-blue-400', dot: 'bg-blue-500' },
  CANCELLED: { bg: 'bg-red-50 dark:bg-red-900/30', text: 'text-red-600 dark:text-red-400', dot: 'bg-red-400' },
  RESCHEDULED: { bg: 'bg-amber-50 dark:bg-amber-900/30', text: 'text-amber-700 dark:text-amber-400', dot: 'bg-amber-500' },
  NO_SHOW: { bg: 'bg-amber-50 dark:bg-amber-900/30', text: 'text-amber-700 dark:text-amber-400', dot: 'bg-amber-500' },
};

const STATUS_LABELS = {
  CONFIRMED: 'Confirmed',
  CANCELLED: 'Cancelled',
  RESCHEDULED: 'Rescheduled',
  COMPLETED: 'Attended',
  NO_SHOW: 'No Show',
};

export default function PatientCRM() {
  const { user } = useAuth();
  const { confirm, prompt, toast } = useModal();
  const tz = user?.timezone || 'America/Chicago';
  const [patients, setPatients] = useState([]);
  const [selectedPatientId, setSelectedPatientId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('recent');
  const [showTestData, setShowTestData] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [deleting, setDeleting] = useState(false);
  const searchTimeout = useRef(null);

  const fetchPatients = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('search', search.trim());
      params.set('sort', sort);
      if (showTestData) params.set('include_test', 'true');
      const url = `/api/patients${params.toString() ? '?' + params.toString() : ''}`;
      const data = await apiFetch(url);
      setPatients(data || []);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load patients');
    } finally {
      setLoading(false);
    }
  }, [search, sort, showTestData]);

  useEffect(() => {
    setLoading(true);
    // Debounce search
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => fetchPatients(), 300);
    return () => clearTimeout(searchTimeout.current);
  }, [fetchPatients]);

  // Clear selections when patient list changes
  useEffect(() => {
    setSelectedIds(new Set());
  }, [patients]);

  function toggleSelect(id) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selectedIds.size === patients.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(patients.map((p) => p.id)));
    }
  }

  async function handleBulkDelete() {
    const count = selectedIds.size;
    if (count === 0) return;

    const names = patients
      .filter((p) => selectedIds.has(p.id))
      .map((p) => p.name || p.phone);

    // Step 1: First confirmation
    const confirmed = await confirm({
      title: `Delete ${count} patient${count > 1 ? 's' : ''}?`,
      message: `This will permanently delete ${count > 3 ? `${count} patients` : names.join(', ')} and all their appointments, waitlist entries, and SMS messages. This cannot be undone.`,
      confirmText: 'Continue',
      variant: 'danger',
    });
    if (!confirmed) return;

    // Step 2: Type DELETE to confirm
    const typed = await prompt({
      title: 'Final confirmation',
      message: `Type DELETE to permanently remove ${count} patient${count > 1 ? 's' : ''} and all related data.`,
      placeholder: 'Type DELETE',
      confirmText: 'Delete permanently',
      variant: 'danger',
    });
    if (typed !== 'DELETE') {
      if (typed !== null) toast.warning('Deletion cancelled — you must type DELETE exactly.');
      return;
    }

    setDeleting(true);
    try {
      const result = await apiFetch('/api/patients/bulk-delete', {
        method: 'POST',
        body: { patient_ids: [...selectedIds] },
      });
      toast.success(
        `Deleted ${result.deleted.patients} patient${result.deleted.patients > 1 ? 's' : ''} and ${result.total - result.deleted.patients} related records.`
      );
      setSelectedIds(new Set());
      setSelectMode(false);
      await fetchPatients();
    } catch (err) {
      toast.error(err.message || 'Failed to delete patients');
    } finally {
      setDeleting(false);
    }
  }

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
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl md:text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Users className="w-6 md:w-7 h-6 md:h-7 text-primary-500" />
            Patients
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Built automatically from AI bookings and SMS.
          </p>
        </div>
        <button
          onClick={() => {
            setSelectMode(!selectMode);
            if (selectMode) setSelectedIds(new Set());
          }}
          className={`flex items-center gap-1.5 px-4 py-2.5 border rounded-lg text-sm font-medium transition-colors ${
            selectMode
              ? 'bg-primary-50 dark:bg-primary-900/30 border-primary-300 dark:border-primary-700 text-primary-700 dark:text-primary-400'
              : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50'
          }`}
        >
          <CheckCircle2 className="w-4 h-4" />
          {selectMode ? 'Cancel Selection' : 'Select'}
        </button>
      </div>

      {/* Search & Sort bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or phone..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 dark:bg-gray-700 dark:text-white"
          />
        </div>
        <div className="flex items-center gap-2">
          <TestDataToggle enabled={showTestData} onChange={setShowTestData} />
          <ThemedSelect
            value={sort}
            onChange={setSort}
            options={[
              { value: 'recent', label: 'Most Recent' },
              { value: 'name', label: 'Name A-Z' },
              { value: 'visits', label: 'Most Visits' },
            ]}
            className="w-44"
          />
        </div>
      </div>

      {/* Bulk delete toolbar — shows when patients are selected */}
      {selectMode && selectedIds.size > 0 && (
        <div className="flex items-center justify-between bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl px-4 py-3">
          <span className="text-sm font-medium text-red-700 dark:text-red-400">
            {selectedIds.size} patient{selectedIds.size > 1 ? 's' : ''} selected
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedIds(new Set())}
              className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              Clear
            </button>
            <button
              onClick={handleBulkDelete}
              disabled={deleting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500 text-white rounded-lg text-xs font-medium hover:bg-red-600 disabled:opacity-50 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {deleting ? 'Deleting...' : `Delete ${selectedIds.size}`}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
        </div>
      ) : patients.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Users className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
            {search ? 'No patients match your search' : 'No patients yet'}
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {search
              ? 'Try a different name or phone number.'
              : 'Patient records are created automatically when the AI books appointments.'}
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          {/* Table header — desktop only */}
          <div className="hidden md:flex items-center gap-3 px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            {selectMode && (
              <div className="shrink-0 w-5">
                <input
                  type="checkbox"
                  checked={selectedIds.size === patients.length && patients.length > 0}
                  onChange={toggleSelectAll}
                  className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-primary-500 focus:ring-primary-500 cursor-pointer"
                />
              </div>
            )}
            <div className="grid grid-cols-12 gap-3 flex-1">
              <div className="col-span-4">Patient</div>
              <div className="col-span-2">Contact</div>
              <div className="col-span-2 text-center">Visits</div>
              <div className="col-span-2">Last Seen</div>
              <div className="col-span-2 text-center">Upcoming</div>
            </div>
          </div>

          {/* Rows — desktop table / mobile card */}
          {patients.map((p, idx) => (
            <div
              key={p.id}
              className={`w-full hover:bg-primary-50/50 dark:hover:bg-primary-900/20 transition-colors ${
                idx > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''
              } ${selectMode && selectedIds.has(p.id) ? 'bg-red-50/50 dark:bg-red-900/10' : ''}`}
            >
              {/* Desktop row */}
              <div className="hidden md:flex items-center gap-3 px-4 py-3.5">
                {selectMode && (
                  <div className="shrink-0 w-5" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(p.id)}
                      onChange={() => toggleSelect(p.id)}
                      className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-primary-500 focus:ring-primary-500 cursor-pointer"
                    />
                  </div>
                )}
                <button
                  onClick={() => setSelectedPatientId(p.id)}
                  className="grid grid-cols-12 gap-3 flex-1 items-center text-left"
                >
                  {/* Name + type */}
                  <div className="col-span-4 flex items-center gap-3 min-w-0">
                    <div
                      className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${
                        p.is_new_patient
                          ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400'
                          : 'bg-primary-100 text-primary-700 dark:bg-primary-900/50 dark:text-primary-400'
                      }`}
                    >
                      {(p.name || '?').charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-gray-900 dark:text-white truncate flex items-center gap-1.5">
                        {p.name}
                        {p.is_test && <TestBadge />}
                      </p>
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
                  <div className="col-span-2 text-xs text-gray-500 dark:text-gray-400 space-y-0.5 min-w-0">
                    <p className="truncate">{p.phone}</p>
                    {p.email && <p className="truncate text-gray-400">{p.email}</p>}
                  </div>
                  <div className="col-span-2 text-center">
                    <span className="text-sm font-semibold text-gray-900 dark:text-white">{p.visit_count}</span>
                    {p.no_show_count > 0 && (
                      <span className="ml-1 text-xs text-red-400">({p.no_show_count} NS)</span>
                    )}
                  </div>
                  <div className="col-span-2 text-xs text-gray-500 dark:text-gray-400">
                    {p.last_appointment_at
                      ? fmtRelative(p.last_appointment_at, tz)
                      : <span className="text-gray-300">Never</span>}
                  </div>
                  <div className="col-span-2 flex items-center justify-center gap-1">
                    {p.upcoming_count > 0 ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium">
                        <Calendar className="w-3 h-3" />
                        {p.upcoming_count}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-300">—</span>
                    )}
                    <ChevronRight className="w-4 h-4 text-gray-300" />
                  </div>
                </button>
              </div>

              {/* Mobile card */}
              <div className="md:hidden px-4 py-3.5 flex items-center gap-3">
                {selectMode && (
                  <div onClick={(e) => e.stopPropagation()} className="shrink-0">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(p.id)}
                      onChange={() => toggleSelect(p.id)}
                      className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-primary-500 focus:ring-primary-500 cursor-pointer"
                    />
                  </div>
                )}
                <button
                  onClick={() => setSelectedPatientId(p.id)}
                  className="flex-1 flex items-center gap-3 text-left min-w-0"
                >
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${
                      p.is_new_patient
                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400'
                        : 'bg-primary-100 text-primary-700 dark:bg-primary-900/50 dark:text-primary-400'
                    }`}
                  >
                    {(p.name || '?').charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">{p.name}</p>
                      {p.is_test && <TestBadge />}
                      {p.is_new_patient && (
                        <span className="text-[10px] bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded-full font-medium shrink-0">New</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">{p.phone}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                      <span>{p.visit_count} visit{p.visit_count !== 1 ? 's' : ''}</span>
                      {p.upcoming_count > 0 && (
                        <span className="text-green-600 dark:text-green-400 font-medium">{p.upcoming_count} upcoming</span>
                      )}
                      {p.last_appointment_at && (
                        <span>{fmtRelative(p.last_appointment_at, tz)}</span>
                      )}
                    </div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-gray-300 shrink-0" />
                </button>
              </div>
            </div>
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
  const { toast, confirm, prompt } = useModal();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('appointments');
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [deletingPatient, setDeletingPatient] = useState(false);

  // Status update state (mirrors AppointmentManager.jsx)
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null); // { action, id, status }
  const [expandedApptId, setExpandedApptId] = useState(null);

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

  // ── Appointment status handlers (mirror AppointmentManager.jsx) ──────────
  async function handleStatusUpdate(id, newStatus) {
    setUpdatingStatus(true);
    try {
      await apiFetch(`/api/appointments/${id}`, {
        method: 'PATCH',
        body: { status: newStatus },
      });
      setConfirmAction(null);
      await fetchProfile();
    } catch (err) {
      console.error('Status update failed:', err);
      toast.error(err.message || 'Status update failed');
    } finally {
      setUpdatingStatus(false);
    }
  }

  async function handleCancelAppt(id) {
    setUpdatingStatus(true);
    try {
      await apiFetch(`/api/appointments/${id}/cancel`, { method: 'POST' });
      setConfirmAction(null);
      await fetchProfile();
    } catch (err) {
      console.error('Cancel failed:', err);
      toast.error(err.message || 'Cancel failed');
    } finally {
      setUpdatingStatus(false);
    }
  }

  async function handleDeletePatient() {
    const name = data?.patient?.name || 'this patient';

    // Step 1: First confirmation
    const confirmed = await confirm({
      title: `Delete ${name}?`,
      message: `This will permanently delete ${name} and all their appointments, waitlist entries, and SMS messages. This action cannot be undone.`,
      confirmText: 'Continue',
      variant: 'danger',
    });
    if (!confirmed) return;

    // Step 2: Type DELETE to confirm
    const typed = await prompt({
      title: 'Final confirmation',
      message: `Type DELETE to permanently remove ${name} and all related data.`,
      placeholder: 'Type DELETE',
      confirmText: 'Delete permanently',
      variant: 'danger',
    });
    if (typed !== 'DELETE') {
      if (typed !== null) toast.warning('Deletion cancelled — you must type DELETE exactly.');
      return;
    }

    setDeletingPatient(true);
    try {
      const result = await apiFetch(`/api/patients/${patientId}`, { method: 'DELETE' });
      toast.success(
        `Deleted ${result.patient_name} and ${result.total - 1} related records.`
      );
      onBack(); // Return to patient list
    } catch (err) {
      toast.error(err.message || 'Failed to delete patient');
    } finally {
      setDeletingPatient(false);
    }
  }

  function isPastAppointment(apt) {
    return new Date(apt.scheduled_at) < new Date();
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
        <button onClick={onBack} className="flex items-center gap-2 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-4">
          <ArrowLeft className="w-4 h-4" /> Back to patients
        </button>
        <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500" />
          <p className="text-sm text-red-700 dark:text-red-400">{error || 'Patient not found.'}</p>
        </div>
      </div>
    );
  }

  const p = data.patient;
  const appointments = data.appointments || [];
  const smsMessages = data.sms_messages || [];

  const upcomingAppts = appointments.filter(
    (a) => a.status === 'CONFIRMED' && new Date(a.scheduled_at) > new Date()
  );
  const pastAppts = appointments.filter(
    (a) => a.status !== 'CONFIRMED' || new Date(a.scheduled_at) <= new Date()
  );

  const TABS = [
    { key: 'appointments', label: 'Appointments', icon: Calendar, count: appointments.length },
    { key: 'sms', label: 'SMS', icon: MessageSquare, count: smsMessages.length },
  ];

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-4 md:space-y-6">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-2 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors text-sm"
      >
        <ArrowLeft className="w-4 h-4" /> All Patients
      </button>

      {saved && (
        <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-xl p-3 flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <span className="text-sm text-green-700 dark:text-green-400">Patient updated.</span>
        </div>
      )}

      {/* Patient header card */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 md:p-6">
        <div className="flex flex-col sm:flex-row items-start gap-4">
          {/* Avatar */}
          <div
            className={`w-12 h-12 md:w-14 md:h-14 rounded-full flex items-center justify-center text-lg md:text-xl font-bold shrink-0 ${
              p.is_new_patient
                ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400'
                : 'bg-primary-100 text-primary-700 dark:bg-primary-900/50 dark:text-primary-400'
            }`}
          >
            {(p.name || '?').charAt(0).toUpperCase()}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">{p.name}</h2>
              {p.is_new_patient ? (
                <span className="px-2 py-0.5 bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-400 rounded-full text-xs font-medium">
                  New Patient
                </span>
              ) : (
                <span className="px-2 py-0.5 bg-primary-50 dark:bg-primary-900/50 text-primary-700 dark:text-primary-400 rounded-full text-xs font-medium">
                  Returning · {p.visit_count} visits
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 mt-2 text-sm text-gray-500 dark:text-gray-400 flex-wrap">
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
            </div>

            {/* Quick stats */}
            <div className="flex items-center gap-2 md:gap-4 mt-3 flex-wrap">
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

          {/* Actions */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => {
                setEditing(!editing);
                setEditForm({
                  allergies: p.allergies || '',
                  notes: p.notes || '',
                });
              }}
              className="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
            >
              {editing ? 'Cancel' : 'Edit Notes'}
            </button>
            <button
              onClick={handleDeletePatient}
              disabled={deletingPatient}
              className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 transition-colors"
              title="Delete patient and all related data"
            >
              <Trash2 className="w-4 h-4" />
              {deletingPatient ? 'Deleting...' : 'Delete'}
            </button>
          </div>
        </div>

        {/* Edit form */}
        {editing && (
          <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Allergies</label>
                <input
                  type="text"
                  value={editForm.allergies || ''}
                  onChange={(e) => setEditForm((f) => ({ ...f, allergies: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm outline-none focus:border-primary-500 dark:bg-gray-700 dark:text-white"
                  placeholder="Latex, Penicillin, etc."
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Receptionist Notes</label>
              <textarea
                value={editForm.notes || ''}
                onChange={(e) => setEditForm((f) => ({ ...f, notes: e.target.value }))}
                rows={2}
                className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm outline-none focus:border-primary-500 resize-none dark:bg-gray-700 dark:text-white"
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
          <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700 flex gap-6 text-sm">
            {p.allergies && (
              <div>
                <span className="text-xs font-medium text-red-500 uppercase tracking-wide">Allergies</span>
                <p className="text-gray-700 dark:text-gray-300 mt-0.5">{p.allergies}</p>
              </div>
            )}
            {p.notes && (
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Notes</span>
                <p className="text-gray-700 dark:text-gray-300 mt-0.5">{p.notes}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-gray-200 dark:border-gray-700">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-primary-500 text-primary-700 dark:text-primary-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
              <span
                className={`px-1.5 py-0.5 rounded-full text-xs ${
                  isActive ? 'bg-primary-100 dark:bg-primary-900/50 text-primary-700 dark:text-primary-400' : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
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
        <AppointmentsTab
          upcoming={upcomingAppts}
          past={pastAppts}
          tz={tz}
          expandedApptId={expandedApptId}
          setExpandedApptId={setExpandedApptId}
          isPastAppointment={isPastAppointment}
          setConfirmAction={setConfirmAction}
          updatingStatus={updatingStatus}
        />
      )}
      {activeTab === 'sms' && <SMSTab messages={smsMessages} tz={tz} />}

      {/* Confirmation modal (mirrors AppointmentManager.jsx) */}
      {confirmAction && (
        <div
          className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
          onClick={() => setConfirmAction(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
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
                    handleCancelAppt(confirmAction.id);
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


// ── Sub-components ──────────────────────────────────────────────────────────

function StatBadge({ label, value, icon: Icon, color = 'gray' }) {
  const colors = {
    gray: 'bg-gray-50 dark:bg-gray-700/50 text-gray-700 dark:text-gray-300',
    green: 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400',
  };
  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg ${colors[color] || colors.gray}`}>
      <Icon className="w-3.5 h-3.5 opacity-50" />
      <span className="text-xs font-medium">{value}</span>
      <span className="text-xs text-gray-400">{label}</span>
    </div>
  );
}

function AppointmentsTab({
  upcoming,
  past,
  tz,
  expandedApptId,
  setExpandedApptId,
  isPastAppointment,
  setConfirmAction,
  updatingStatus,
}) {
  const rowProps = {
    tz,
    expandedApptId,
    setExpandedApptId,
    isPastAppointment,
    setConfirmAction,
    updatingStatus,
  };
  return (
    <div className="space-y-4">
      {upcoming.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
            <Calendar className="w-4 h-4 text-green-500" />
            Upcoming ({upcoming.length})
          </h4>
          <div className="space-y-2">
            {upcoming.map((a) => (
              <AppointmentRow key={a.id} appt={a} {...rowProps} />
            ))}
          </div>
        </div>
      )}
      {past.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
            <Clock className="w-4 h-4 text-gray-400" />
            History ({past.length})
          </h4>
          <div className="space-y-2">
            {past.map((a) => (
              <AppointmentRow key={a.id} appt={a} {...rowProps} />
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

function AppointmentRow({
  appt,
  tz,
  expandedApptId,
  setExpandedApptId,
  isPastAppointment,
  setConfirmAction,
  updatingStatus,
}) {
  const status = STATUS_COLORS[appt.status] || STATUS_COLORS.CONFIRMED;
  const isExpanded = expandedApptId === appt.id;
  const isPast = isPastAppointment(appt);

  // Decide whether any actions are available for this appointment
  const hasPastPendingActions = isPast && appt.status === 'CONFIRMED';
  const hasCorrectAttended = appt.status === 'NO_SHOW';
  const hasCorrectNoShow = appt.status === 'COMPLETED';
  const hasCancel = appt.status === 'CONFIRMED' && !isPast;
  const hasAnyActions =
    hasPastPendingActions || hasCorrectAttended || hasCorrectNoShow || hasCancel;
  const hasHistory = appt.status_history && appt.status_history.length > 0;
  const isExpandable = hasAnyActions || hasHistory;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      <button
        type="button"
        onClick={() => isExpandable && setExpandedApptId(isExpanded ? null : appt.id)}
        disabled={!isExpandable}
        className={`w-full p-3 flex items-center gap-4 text-left transition-colors ${
          isExpandable ? 'hover:bg-gray-50 dark:hover:bg-gray-700/40 cursor-pointer' : 'cursor-default'
        }`}
      >
        <div className={`w-2 h-2 rounded-full ${status.dot} shrink-0`}></div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-900 dark:text-white">
              {appt.appointment_type_display || appt.appointment_type?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
            </span>
            <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${status.bg} ${status.text}`}>
              {STATUS_LABELS[appt.status] || appt.status}
            </span>
            {appt.booked_via === 'AI' && (
              <span className="px-1.5 py-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded text-xs font-medium">
                AI Booked
              </span>
            )}
            {appt.confirmed_by_patient === true && (
              <span className="px-1.5 py-0.5 bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400 rounded text-xs font-medium">
                ✓ Confirmed
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            {appt.scheduled_at ? formatDateTime(appt.scheduled_at, tz) : ''}{' '}
            · {appt.duration_minutes} min
            {appt.provider_name && (
              <span className="ml-1">· <Stethoscope className="w-3 h-3 inline -mt-0.5" /> {appt.provider_name}</span>
            )}
          </p>
        </div>
        {isExpandable && (
          <ChevronRight
            className={`w-4 h-4 text-gray-300 shrink-0 transition-transform ${
              isExpanded ? 'rotate-90' : ''
            }`}
          />
        )}
      </button>

      {/* Expanded section — history + actions */}
      {isExpanded && isExpandable && (
        <div className="border-t border-gray-100 dark:border-gray-700 p-3 bg-gray-50 dark:bg-gray-700/30 space-y-3">
          {/* Status History Timeline */}
          {hasHistory && (
            <div>
              <p className="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">
                History
              </p>
              <div className="relative pl-4 space-y-2">
                <div className="absolute left-[5px] top-0.5 bottom-0.5 w-px bg-gray-200 dark:bg-gray-600" />
                {appt.status_history.map((entry, idx) => {
                  const isCreation = !entry.old_status;
                  const label = STATUS_LABELS[entry.new_status] || entry.new_status;
                  return (
                    <div key={idx} className="relative flex items-start gap-2">
                      <div className={`absolute -left-4 top-0.5 w-2 h-2 rounded-full border-2 border-white dark:border-gray-700 ${
                        entry.new_status === 'CONFIRMED' ? 'bg-green-400' :
                        entry.new_status === 'COMPLETED' ? 'bg-emerald-500' :
                        entry.new_status === 'CANCELLED' ? 'bg-red-400' :
                        entry.new_status === 'NO_SHOW' ? 'bg-amber-400' :
                        'bg-blue-400'
                      }`} />
                      <div className="min-w-0">
                        <p className="text-[11px] text-gray-600 dark:text-gray-400">
                          {isCreation ? (
                            <span className="text-green-600 dark:text-green-400">Booked</span>
                          ) : (
                            <>{STATUS_LABELS[entry.old_status] || entry.old_status} → <span className={
                              entry.new_status === 'COMPLETED' ? 'text-emerald-600 dark:text-emerald-400' :
                              entry.new_status === 'CANCELLED' ? 'text-red-600 dark:text-red-400' :
                              entry.new_status === 'NO_SHOW' ? 'text-amber-600 dark:text-amber-400' :
                              'text-blue-600 dark:text-blue-400'
                            }>{label}</span></>
                          )}
                          {entry.created_at && (
                            <span className="text-gray-400 dark:text-gray-500 ml-1">
                              · {fmtRelative(entry.created_at, tz)}
                            </span>
                          )}
                        </p>
                        {entry.note && (
                          <p className="text-[10px] text-gray-400 dark:text-gray-500 italic mt-0.5">{entry.note}</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {hasPastPendingActions && (
            <>
              <p className="text-xs text-amber-600 dark:text-amber-400 font-medium">
                This appointment is in the past. Please update the outcome:
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() =>
                    setConfirmAction({ action: 'attended', id: appt.id, status: 'COMPLETED' })
                  }
                  disabled={updatingStatus}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 rounded-lg text-xs font-medium hover:bg-emerald-100 dark:hover:bg-emerald-900/50 disabled:opacity-50 transition-colors"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Attended
                </button>
                <button
                  onClick={() =>
                    setConfirmAction({ action: 'no-show', id: appt.id, status: 'NO_SHOW' })
                  }
                  disabled={updatingStatus}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 rounded-lg text-xs font-medium hover:bg-amber-100 dark:hover:bg-amber-900/50 disabled:opacity-50 transition-colors"
                >
                  <XCircle className="w-3.5 h-3.5" />
                  No Show
                </button>
              </div>
            </>
          )}

          {hasCorrectAttended && (
            <button
              onClick={() =>
                setConfirmAction({ action: 'correct-attended', id: appt.id, status: 'COMPLETED' })
              }
              disabled={updatingStatus}
              className="w-full flex items-center justify-center gap-1.5 py-2 px-3 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 rounded-lg text-xs font-medium hover:bg-emerald-100 dark:hover:bg-emerald-900/50 disabled:opacity-50 transition-colors"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Correct to Attended
            </button>
          )}

          {hasCorrectNoShow && (
            <button
              onClick={() =>
                setConfirmAction({ action: 'correct-no-show', id: appt.id, status: 'NO_SHOW' })
              }
              disabled={updatingStatus}
              className="w-full flex items-center justify-center gap-1.5 py-2 px-3 bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 rounded-lg text-xs font-medium hover:bg-amber-100 dark:hover:bg-amber-900/50 disabled:opacity-50 transition-colors"
            >
              <XCircle className="w-3.5 h-3.5" />
              Correct to No Show
            </button>
          )}

          {hasCancel && (
            <button
              onClick={() => setConfirmAction({ action: 'cancel', id: appt.id })}
              disabled={updatingStatus}
              className="w-full py-2 px-3 bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded-lg text-xs font-medium hover:bg-red-100 dark:hover:bg-red-900/50 disabled:opacity-50 transition-colors"
            >
              Cancel Appointment
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function SMSTab({ messages, tz }) {
  if (messages.length === 0) {
    return <EmptyState icon={MessageSquare} message="No SMS messages." />;
  }
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 max-h-[500px] overflow-y-auto overscroll-y-contain p-4 space-y-2" style={{ WebkitOverflowScrolling: 'touch' }}>
      {/* Messages are newest first from API, reverse for chat order */}
      {[...messages].reverse().map((msg) => {
        const isOutbound = msg.direction === 'OUTBOUND';
        return (
          <div key={msg.id} className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[70%] rounded-2xl px-3 py-2 ${
                isOutbound
                  ? 'bg-primary-500 text-white rounded-br-md'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-bl-md'
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
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-8 text-center">
      <Icon className="w-10 h-10 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-500 dark:text-gray-400">{message}</p>
    </div>
  );
}


// ── Helpers ─────────────────────────────────────────────────────────────────
// formatRelativeTime is now imported from lib/timezone.js as fmtRelative
