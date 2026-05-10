import React, { useState, useEffect, useCallback } from 'react';
import {
  ClipboardList,
  X,
  RefreshCw,
  AlertCircle,
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
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatDate } from '../lib/timezone';

const STATUS_CONFIG = {
  WAITING: {
    label: 'Waiting',
    icon: Clock,
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    border: 'border-blue-200',
    dot: 'bg-blue-500',
  },
  NOTIFIED: {
    label: 'Notified',
    icon: Bell,
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    border: 'border-amber-200',
    dot: 'bg-amber-500',
  },
  BOOKED: {
    label: 'Booked',
    icon: CheckCircle2,
    bg: 'bg-green-50',
    text: 'text-green-700',
    border: 'border-green-200',
    dot: 'bg-green-500',
  },
  EXPIRED: {
    label: 'Expired',
    icon: Timer,
    bg: 'bg-gray-50',
    text: 'text-gray-500',
    border: 'border-gray-200',
    dot: 'bg-gray-400',
  },
  CANCELLED: {
    label: 'Cancelled',
    icon: XCircle,
    bg: 'bg-red-50',
    text: 'text-red-600',
    border: 'border-red-200',
    dot: 'bg-red-400',
  },
};

export default function WaitlistView() {
  const { user } = useAuth();
  const tz = user?.timezone || 'America/Chicago';
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [refreshing, setRefreshing] = useState(false);

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
    if (!confirm('Cancel this waitlist entry? The patient will no longer be notified when a slot opens.'))
      return;
    try {
      await apiFetch(`/api/waitlist/${entryId}`, { method: 'DELETE' });
      await fetchEntries();
    } catch (err) {
      setError(err.message || 'Failed to cancel entry');
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
          <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <ClipboardList className="w-7 h-7 text-primary-500" />
            Waitlist
          </h2>
          <p className="text-gray-500 mt-1">
            Patients waiting for appointment openings. They're auto-notified when a cancellation
            matches their preferences.
          </p>
        </div>
        <button
          onClick={() => fetchEntries(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
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
                  ? `${cfg.bg} ${cfg.border} ring-2 ring-offset-1 ring-primary-300`
                  : 'bg-white border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Icon className={`w-4 h-4 ${isActive ? cfg.text : 'text-gray-400'}`} />
                <span className={`text-xs font-medium ${isActive ? cfg.text : 'text-gray-500'}`}>
                  {cfg.label}
                </span>
              </div>
              <p className={`text-2xl font-bold mt-1 ${isActive ? cfg.text : 'text-gray-900'}`}>
                {count}
              </p>
            </button>
          );
        })}
      </div>

      {/* Filter indicator */}
      {filterStatus && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Filter className="w-4 h-4" />
          Showing <strong>{filterStatus}</strong> entries
          <button
            onClick={() => setFilterStatus('')}
            className="ml-1 px-2 py-0.5 bg-gray-100 rounded-full text-xs hover:bg-gray-200 transition-colors"
          >
            Clear
          </button>
        </div>
      )}

      {/* Entries list */}
      {entries.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <ClipboardList className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            {filterStatus ? 'No matching entries' : 'Waitlist is empty'}
          </h3>
          <p className="text-sm text-gray-500">
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
                className="bg-white rounded-xl border border-gray-200 p-4 hover:border-gray-300 transition-colors"
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
                      <span className="font-semibold text-gray-900">{entry.patient_name}</span>
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bg} ${cfg.text}`}
                      >
                        <div className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`}></div>
                        {cfg.label}
                      </span>
                    </div>

                    <div className="flex items-center gap-4 mt-1.5 text-sm text-gray-500 flex-wrap">
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
                    <div className="flex items-center gap-4 mt-1 text-xs text-gray-400">
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

                  {/* Action */}
                  {entry.status === 'WAITING' || entry.status === 'NOTIFIED' ? (
                    <button
                      onClick={() => handleCancel(entry.id)}
                      className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"
                      title="Cancel entry"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
