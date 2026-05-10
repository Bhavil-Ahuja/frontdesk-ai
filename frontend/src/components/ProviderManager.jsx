import React, { useState, useEffect, useCallback } from 'react';
import {
  UserPlus,
  Users,
  Pencil,
  Trash2,
  Save,
  X,
  Calendar,
  Clock,
  Stethoscope,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

const EMPTY_PROVIDER = {
  name: '',
  title: '',
  appointment_types: [],
  calendar_id: '',
  business_hours_override: null,
};

export default function ProviderManager() {
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingId, setEditingId] = useState(null); // provider id or '__new__'
  const [form, setForm] = useState({ ...EMPTY_PROVIDER });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [tenantAppointmentTypes, setTenantAppointmentTypes] = useState([]);
  const [expandedId, setExpandedId] = useState(null);

  const fetchProviders = useCallback(async () => {
    try {
      const data = await apiFetch('/api/providers');
      setProviders(data || []);
    } catch (err) {
      setError(err.message || 'Failed to load providers');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAppointmentTypes = useCallback(async () => {
    try {
      const config = await apiFetch('/api/config');
      setTenantAppointmentTypes(config.appointment_types || []);
    } catch {
      // Non-critical — appointment type picker just won't be populated
    }
  }, []);

  useEffect(() => {
    fetchProviders();
    fetchAppointmentTypes();
  }, [fetchProviders, fetchAppointmentTypes]);

  function startCreate() {
    setEditingId('__new__');
    setForm({ ...EMPTY_PROVIDER });
    setError(null);
  }

  function startEdit(provider) {
    setEditingId(provider.id);
    setForm({
      name: provider.name || '',
      title: provider.title || '',
      appointment_types: provider.appointment_types || [],
      calendar_id: provider.calendar_id || '',
      business_hours_override: provider.business_hours_override || null,
    });
    setError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm({ ...EMPTY_PROVIDER });
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError('Provider name is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: form.name.trim(),
        title: form.title.trim() || null,
        appointment_types: form.appointment_types.length > 0 ? form.appointment_types : null,
        calendar_id: form.calendar_id.trim() || null,
        business_hours_override: form.business_hours_override,
      };

      if (editingId === '__new__') {
        await apiFetch('/api/providers', { method: 'POST', body: payload });
      } else {
        await apiFetch(`/api/providers/${editingId}`, { method: 'PUT', body: payload });
      }
      setEditingId(null);
      setForm({ ...EMPTY_PROVIDER });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      await fetchProviders();
    } catch (err) {
      setError(err.message || 'Failed to save provider.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(providerId) {
    if (!confirm('Deactivate this provider? They will no longer appear in scheduling.')) return;
    try {
      await apiFetch(`/api/providers/${providerId}`, { method: 'DELETE' });
      await fetchProviders();
    } catch (err) {
      setError(err.message || 'Failed to deactivate provider.');
    }
  }

  function toggleAppointmentType(key) {
    setForm((f) => {
      const types = [...(f.appointment_types || [])];
      const idx = types.indexOf(key);
      if (idx >= 0) {
        types.splice(idx, 1);
      } else {
        types.push(key);
      }
      return { ...f, appointment_types: types };
    });
  }

  function toggleHoursOverride() {
    setForm((f) => {
      if (f.business_hours_override) {
        return { ...f, business_hours_override: null };
      }
      // Initialize with standard hours
      return {
        ...f,
        business_hours_override: {
          monday: { open: '08:00', close: '18:00' },
          tuesday: { open: '08:00', close: '18:00' },
          wednesday: { open: '08:00', close: '18:00' },
          thursday: { open: '08:00', close: '18:00' },
          friday: { open: '08:00', close: '18:00' },
          saturday: null,
          sunday: null,
        },
      };
    });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Users className="w-7 h-7 text-primary-500" />
            Providers
          </h2>
          <p className="text-gray-500 mt-1">
            Manage practitioners and staff members. Each provider can have
            their own calendar and appointment types.
          </p>
        </div>
        {editingId === null && (
          <button
            onClick={startCreate}
            className="flex items-center gap-2 px-4 py-2.5 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 transition-colors shadow-sm"
          >
            <UserPlus className="w-4 h-4" />
            Add Provider
          </button>
        )}
      </div>

      {saved && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-green-500 shrink-0" />
          <p className="text-sm text-green-700">Provider saved successfully.</p>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Create / Edit form */}
      {editingId !== null && (
        <div className="bg-white rounded-xl border border-primary-200 p-6 space-y-4 shadow-sm">
          <h3 className="text-lg font-semibold text-gray-900">
            {editingId === '__new__' ? 'New Provider' : 'Edit Provider'}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Dr. Sarah Patel"
                className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Title / Credentials
              </label>
              <input
                type="text"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="DDS, DMD, RDH, etc."
                className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20"
              />
            </div>
          </div>

          {/* Appointment types */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5 flex items-center gap-1.5">
              <Stethoscope className="w-4 h-4 text-gray-400" />
              Appointment Types
            </label>
            <p className="text-xs text-gray-400 mb-2">
              Select which appointment types this provider handles. Leave empty for all types.
            </p>
            {tenantAppointmentTypes.length === 0 ? (
              <p className="text-xs text-amber-600 bg-amber-50 px-3 py-2 rounded-lg">
                No appointment types configured yet. Go to Agent Config → Appointment Types to add some.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {tenantAppointmentTypes.map((at) => {
                  const selected = (form.appointment_types || []).includes(at.key);
                  return (
                    <button
                      key={at.key}
                      type="button"
                      onClick={() => toggleAppointmentType(at.key)}
                      className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors border ${
                        selected
                          ? 'bg-primary-50 border-primary-300 text-primary-700'
                          : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
                      }`}
                    >
                      {at.label || at.key}
                      {selected && <span className="ml-1">✓</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Calendar ID */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5 flex items-center gap-1.5">
              <Calendar className="w-4 h-4 text-gray-400" />
              Google Calendar ID (optional)
            </label>
            <input
              type="text"
              value={form.calendar_id}
              onChange={(e) => setForm((f) => ({ ...f, calendar_id: e.target.value }))}
              placeholder="provider-email@gmail.com or calendar ID"
              className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20"
            />
            <p className="text-xs text-gray-400 mt-1">
              If blank, this provider shares the practice's primary Google Calendar.
            </p>
          </div>

          {/* Business hours override */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-4 h-4 text-gray-400" />
              <label className="text-sm font-medium text-gray-700">Custom Business Hours</label>
              <button
                type="button"
                onClick={toggleHoursOverride}
                className={`ml-2 px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  form.business_hours_override
                    ? 'bg-primary-50 text-primary-700 border border-primary-200'
                    : 'bg-gray-100 text-gray-500 border border-gray-200 hover:bg-gray-200'
                }`}
              >
                {form.business_hours_override ? 'Custom Hours Enabled' : 'Use Practice Default'}
              </button>
            </div>
            {form.business_hours_override && (
              <div className="space-y-2 bg-gray-50 rounded-lg p-3 border border-gray-100">
                {DAYS.map((day) => {
                  const hours = form.business_hours_override?.[day];
                  const isOpen = hours !== null && hours !== undefined;
                  return (
                    <div key={day} className="flex items-center gap-3">
                      <span className="w-20 text-xs font-medium text-gray-600 capitalize">
                        {day}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          const bh = { ...(form.business_hours_override || {}) };
                          bh[day] = isOpen ? null : { open: '08:00', close: '18:00' };
                          setForm((f) => ({ ...f, business_hours_override: bh }));
                        }}
                        className={`px-2 py-0.5 rounded-full text-xs font-medium transition-colors ${
                          isOpen
                            ? 'bg-green-100 text-green-700 hover:bg-green-200'
                            : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                        }`}
                      >
                        {isOpen ? 'Open' : 'Off'}
                      </button>
                      {isOpen && (
                        <>
                          <input
                            type="time"
                            value={hours.open}
                            onChange={(e) => {
                              const bh = { ...form.business_hours_override };
                              bh[day] = { ...bh[day], open: e.target.value };
                              setForm((f) => ({ ...f, business_hours_override: bh }));
                            }}
                            className="px-2 py-1 border border-gray-200 rounded-lg text-xs focus:ring-2 focus:ring-primary-500 outline-none"
                          />
                          <span className="text-gray-400 text-xs">to</span>
                          <input
                            type="time"
                            value={hours.close}
                            onChange={(e) => {
                              const bh = { ...form.business_hours_override };
                              bh[day] = { ...bh[day], close: e.target.value };
                              setForm((f) => ({ ...f, business_hours_override: bh }));
                            }}
                            className="px-2 py-1 border border-gray-200 rounded-lg text-xs focus:ring-2 focus:ring-primary-500 outline-none"
                          />
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50 transition-colors"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : 'Save Provider'}
            </button>
            <button
              onClick={cancelEdit}
              className="flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Provider list */}
      {providers.length === 0 && editingId === null ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Users className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-gray-900 mb-1">No providers yet</h3>
          <p className="text-sm text-gray-500 mb-4">
            Add your practitioners so the AI agent can schedule appointments with specific providers.
          </p>
          <button
            onClick={startCreate}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 transition-colors"
          >
            <UserPlus className="w-4 h-4" />
            Add Your First Provider
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((p) => {
            const isExpanded = expandedId === p.id;
            return (
              <div
                key={p.id}
                className={`bg-white rounded-xl border ${
                  p.is_active ? 'border-gray-200' : 'border-red-100 bg-red-50/30'
                } overflow-hidden transition-all`}
              >
                {/* Summary row */}
                <div
                  className="flex items-center gap-4 p-4 cursor-pointer hover:bg-gray-50/50 transition-colors"
                  onClick={() => setExpandedId(isExpanded ? null : p.id)}
                >
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${
                      p.is_active
                        ? 'bg-primary-100 text-primary-700'
                        : 'bg-gray-200 text-gray-500'
                    }`}
                  >
                    {(p.name || '?').charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-900 truncate">{p.name}</span>
                      {p.title && (
                        <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                          {p.title}
                        </span>
                      )}
                      {!p.is_active && (
                        <span className="text-xs text-red-600 bg-red-100 px-2 py-0.5 rounded-full">
                          Inactive
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      {(p.appointment_types || []).length > 0 ? (
                        <span className="text-xs text-gray-500">
                          {p.appointment_types.join(', ')}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400 italic">All appointment types</span>
                      )}
                      {p.calendar_id && (
                        <span className="text-xs text-blue-500 flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          Own calendar
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        startEdit(p);
                      }}
                      className="p-2 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-colors"
                      title="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    {p.is_active && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(p.id);
                        }}
                        className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                        title="Deactivate"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                    {isExpanded ? (
                      <ChevronUp className="w-4 h-4 text-gray-400" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-gray-400" />
                    )}
                  </div>
                </div>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="border-t border-gray-100 px-4 py-3 bg-gray-50/50 text-sm space-y-2">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                          Calendar ID
                        </span>
                        <p className="text-gray-700 mt-0.5">
                          {p.calendar_id || (
                            <span className="italic text-gray-400">Using practice default</span>
                          )}
                        </p>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                          Custom Hours
                        </span>
                        <p className="text-gray-700 mt-0.5">
                          {p.business_hours_override ? 'Yes — custom schedule' : (
                            <span className="italic text-gray-400">Using practice default</span>
                          )}
                        </p>
                      </div>
                    </div>
                    {p.business_hours_override && (
                      <div className="mt-2 grid grid-cols-7 gap-1">
                        {DAYS.map((day) => {
                          const h = p.business_hours_override[day];
                          return (
                            <div
                              key={day}
                              className={`text-center px-1 py-1.5 rounded text-xs ${
                                h ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-400'
                              }`}
                            >
                              <div className="font-medium capitalize">{day.slice(0, 3)}</div>
                              {h ? (
                                <div className="mt-0.5">
                                  {h.open}–{h.close}
                                </div>
                              ) : (
                                <div className="mt-0.5">Off</div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
