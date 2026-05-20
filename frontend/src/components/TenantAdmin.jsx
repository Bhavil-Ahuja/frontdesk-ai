import React, { useState, useEffect } from 'react';
import {
  Shield,
  Building2,
  Clock,
  CheckCircle,
  XCircle,
  PauseCircle,
  PlayCircle,
  Trash2,
  RefreshCw,
  Search,
  Filter,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Mail,
  Phone,
  Globe2,
  Wifi,
  WifiOff,
  AlertCircle,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

const STATUS_CONFIG = {
  PENDING: {
    color: 'bg-amber-100 text-amber-700',
    dot: 'bg-amber-400',
    icon: Clock,
    label: 'Pending',
  },
  APPROVED: {
    color: 'bg-blue-100 text-blue-700',
    dot: 'bg-blue-400',
    icon: CheckCircle,
    label: 'Approved',
  },
  ACTIVE: {
    color: 'bg-green-100 text-green-700',
    dot: 'bg-green-400',
    icon: Wifi,
    label: 'Active',
  },
  SUSPENDED: {
    color: 'bg-red-100 text-red-700',
    dot: 'bg-red-400',
    icon: PauseCircle,
    label: 'Suspended',
  },
  DEACTIVATED: {
    color: 'bg-gray-100 text-gray-500',
    dot: 'bg-gray-400',
    icon: WifiOff,
    label: 'Deactivated',
  },
};

const STATUS_FILTERS = ['ALL', 'PENDING', 'ACTIVE', 'APPROVED', 'SUSPENDED', 'DEACTIVATED'];

export default function TenantAdmin() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [actionLoading, setActionLoading] = useState(null); // tenant_id currently being actioned
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchTenants();
  }, [statusFilter]);

  async function fetchTenants() {
    setLoading(true);
    setError(null);
    try {
      const params = statusFilter !== 'ALL' ? `?status=${statusFilter}` : '';
      const data = await apiFetch(`/api/tenants${params}`);
      setTenants(data);
    } catch (err) {
      console.error('Failed to fetch tenants:', err);
      setError(err.message || 'Failed to load tenants.');
    } finally {
      setLoading(false);
    }
  }

  async function performAction(tenantId, action, method = 'POST') {
    setActionLoading(tenantId);
    try {
      const url =
        action === 'delete'
          ? `/api/tenants/${tenantId}`
          : `/api/tenants/${tenantId}/${action}`;
      await apiFetch(url, { method });
      await fetchTenants();
    } catch (err) {
      console.error(`Action ${action} failed:`, err);
      alert(err.message || 'Action failed.');
    } finally {
      setActionLoading(null);
    }
  }

  // Client-side search filter (over already-fetched tenants)
  const filtered = tenants.filter((t) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      t.business_name.toLowerCase().includes(q) ||
      t.slug.toLowerCase().includes(q) ||
      t.owner_name.toLowerCase().includes(q) ||
      t.owner_email.toLowerCase().includes(q)
    );
  });

  // Stats
  const pendingCount = tenants.filter((t) => t.status === 'PENDING').length;
  const activeCount = tenants.filter((t) => t.status === 'ACTIVE').length;
  const totalCount = tenants.length;

  if (loading && tenants.length === 0) {
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
          <h2 className="text-2xl font-bold text-gray-900">Tenant Management</h2>
          <p className="text-gray-500 mt-1">Approve, manage, and monitor registered businesses</p>
        </div>
        <button
          onClick={fetchTenants}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-blue-50">
              <Building2 className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{totalCount}</p>
              <p className="text-sm text-gray-500">Total Tenants</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-amber-50">
              <Clock className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{pendingCount}</p>
              <p className="text-sm text-gray-500">Pending Approval</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-green-50">
              <Wifi className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{activeCount}</p>
              <p className="text-sm text-gray-500">Active Tenants</p>
            </div>
          </div>
        </div>
      </div>

      {/* Filters row */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by name, slug, owner..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          />
        </div>

        {/* Status filter pills */}
        <div className="flex items-center gap-1 flex-wrap">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                statusFilter === s
                  ? 'bg-primary-500 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {s === 'ALL' ? 'All' : STATUS_CONFIG[s]?.label || s}
              {s === 'PENDING' && pendingCount > 0 && (
                <span className="ml-1 bg-white/30 px-1.5 py-0.5 rounded-full text-[10px]">
                  {pendingCount}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Tenant list */}
      {filtered.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Building2 className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500 text-sm">
            {searchQuery
              ? 'No tenants match your search.'
              : statusFilter !== 'ALL'
              ? `No ${STATUS_CONFIG[statusFilter]?.label?.toLowerCase()} tenants.`
              : 'No tenants registered yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((tenant) => (
            <TenantRow
              key={tenant.id}
              tenant={tenant}
              expanded={expandedId === tenant.id}
              onToggle={() => setExpandedId(expandedId === tenant.id ? null : tenant.id)}
              onAction={(action, method) => performAction(tenant.id, action, method)}
              actionLoading={actionLoading === tenant.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Individual tenant row ────────────────────────────────────────────────────

function TenantRow({ tenant, expanded, onToggle, onAction, actionLoading }) {
  const cfg = STATUS_CONFIG[tenant.status] || STATUS_CONFIG.PENDING;
  const StatusIcon = cfg.icon;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Summary row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 p-4 text-left hover:bg-gray-50 transition-colors"
      >
        {/* Status dot */}
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`}></div>

        {/* Business info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900 truncate">{tenant.business_name}</span>
            <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.color}`}>
              {cfg.label}
            </span>
            {tenant.demo_mode && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-100 text-purple-700">
                Demo
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500">
            <span className="font-mono">{tenant.slug}</span>
            <span>·</span>
            <span>{tenant.owner_name}</span>
            <span>·</span>
            <span>{tenant.owner_email}</span>
          </div>
        </div>

        {/* Integration badges */}
        <div className="hidden md:flex items-center gap-1.5">
          <IntegrationBadge label="Vapi" active={tenant.vapi_configured} />
          <IntegrationBadge label="GCal" active={tenant.google_calendar_connected} />
          <IntegrationBadge label="Twilio" active={tenant.twilio_configured} />
        </div>

        {/* Expand chevron */}
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
        )}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-5 bg-gray-50/50">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: details */}
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Details</h4>
              <DetailRow label="ID" value={tenant.id} mono />
              <DetailRow label="Slug" value={tenant.slug} mono />
              <DetailRow label="Business Type" value={tenant.business_type || '—'} />
              <DetailRow label="Timezone" value={tenant.timezone} />
              <DetailRow label="Plan" value={tenant.plan || '—'} />
              <DetailRow label="Agent Name" value={tenant.agent_name || '—'} />
              <DetailRow
                label="Created"
                value={tenant.created_at ? new Date(tenant.created_at).toLocaleString() : '—'}
              />
              <DetailRow
                label="Updated"
                value={tenant.updated_at ? new Date(tenant.updated_at).toLocaleString() : '—'}
              />
            </div>

            {/* Right: owner + integrations */}
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
                Owner & Integrations
              </h4>
              <DetailRow label="Owner" value={tenant.owner_name} />
              <DetailRow label="Email" value={tenant.owner_email} />
              <DetailRow label="Phone" value={tenant.owner_phone || '—'} />

              <div className="pt-2 space-y-2">
                <IntegrationStatus label="Vapi" configured={tenant.vapi_configured} />
                <IntegrationStatus
                  label={`Google Calendar${tenant.google_calendar_email ? ` (${tenant.google_calendar_email})` : ''}`}
                  configured={tenant.google_calendar_connected}
                />
                <IntegrationStatus label="Twilio" configured={tenant.twilio_configured} />
              </div>
            </div>
          </div>

          {/* Greeting message */}
          {tenant.greeting_message && (
            <div className="mt-4 p-3 bg-white rounded-lg border border-gray-200">
              <p className="text-xs font-medium text-gray-500 mb-1">Greeting Message</p>
              <p className="text-sm text-gray-700 italic">"{tenant.greeting_message}"</p>
            </div>
          )}

          {/* Action buttons */}
          <div className="mt-5 pt-4 border-t border-gray-200 flex flex-wrap gap-2">
            {tenant.status === 'PENDING' && (
              <ActionButton
                icon={CheckCircle}
                label="Approve"
                color="green"
                loading={actionLoading}
                onClick={() => onAction('approve')}
              />
            )}
            {tenant.status === 'ACTIVE' && (
              <ActionButton
                icon={PauseCircle}
                label="Suspend"
                color="amber"
                loading={actionLoading}
                onClick={() => onAction('suspend')}
              />
            )}
            {tenant.status === 'SUSPENDED' && (
              <ActionButton
                icon={PlayCircle}
                label="Reactivate"
                color="blue"
                loading={actionLoading}
                onClick={() => onAction('reactivate')}
              />
            )}
            {tenant.status !== 'DEACTIVATED' && (
              <ActionButton
                icon={Trash2}
                label="Deactivate"
                color="red"
                loading={actionLoading}
                onClick={() => {
                  if (window.confirm(`Deactivate "${tenant.business_name}"? This is a soft delete.`)) {
                    onAction('delete', 'DELETE');
                  }
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Helper sub-components ────────────────────────────────────────────────────

function DetailRow({ label, value, mono }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-xs font-medium text-gray-500 w-24 shrink-0 pt-0.5">{label}</span>
      <span
        className={`text-sm text-gray-800 break-all ${mono ? 'font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded' : ''}`}
      >
        {value}
      </span>
    </div>
  );
}

function IntegrationBadge({ label, active }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-[10px] font-medium ${
        active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
      }`}
    >
      {label}
    </span>
  );
}

function IntegrationStatus({ label, configured }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={`w-2 h-2 rounded-full ${configured ? 'bg-green-400' : 'bg-gray-300'}`}
      ></div>
      <span className="text-sm text-gray-700">{label}</span>
      <span className={`text-xs ${configured ? 'text-green-600' : 'text-gray-400'}`}>
        {configured ? 'Connected' : 'Not configured'}
      </span>
    </div>
  );
}

function ActionButton({ icon: Icon, label, color, loading, onClick }) {
  const colorMap = {
    green: 'bg-green-50 text-green-700 hover:bg-green-100 border-green-200',
    amber: 'bg-amber-50 text-amber-700 hover:bg-amber-100 border-amber-200',
    blue: 'bg-blue-50 text-blue-700 hover:bg-blue-100 border-blue-200',
    red: 'bg-red-50 text-red-700 hover:bg-red-100 border-red-200',
  };

  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50 ${
        colorMap[color] || colorMap.blue
      }`}
    >
      {loading ? (
        <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-current"></div>
      ) : (
        <Icon className="w-3.5 h-3.5" />
      )}
      {label}
    </button>
  );
}
