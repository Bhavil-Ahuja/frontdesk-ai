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
  History,
  MapPin,
  Save,
  PhoneCall,
  MessageSquare,
  BarChart3,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useModal } from '../contexts/ModalContext';

const STATUS_CONFIG = {
  PENDING: {
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400',
    dot: 'bg-amber-400',
    icon: Clock,
    label: 'Pending',
  },
  APPROVED: {
    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400',
    dot: 'bg-blue-400',
    icon: CheckCircle,
    label: 'Approved',
  },
  ACTIVE: {
    color: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400',
    dot: 'bg-green-400',
    icon: Wifi,
    label: 'Active',
  },
  SUSPENDED: {
    color: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-400',
    dot: 'bg-red-400',
    icon: PauseCircle,
    label: 'Suspended',
  },
  DEACTIVATED: {
    color: 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400',
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
  const { toast, confirm, prompt } = useModal();

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
      toast.error(err.message || 'Action failed.');
    } finally {
      setActionLoading(null);
    }
  }

  async function purgeAccount(tenantId, businessName, email) {
    // Step 1: Confirm intent
    const first = await confirm({
      title: 'Permanently Delete Account?',
      message: `This will permanently delete "${businessName}" (${email}) and ALL associated data — appointments, patients, calls, SMS messages.\n\nThis action is IRREVERSIBLE.`,
      confirmText: 'Continue',
      variant: 'danger',
    });
    if (!first) return;

    // Step 2: Type-to-confirm (the business name)
    const typed = await prompt({
      title: 'Type to Confirm',
      message: `Type the exact business name to confirm permanent deletion:`,
      placeholder: businessName,
      confirmText: 'Delete Forever',
      variant: 'danger',
    });
    if (typed === null) return;
    if (typed !== businessName) {
      toast.error('Business name did not match. Deletion cancelled.');
      return;
    }

    setActionLoading(tenantId);
    try {
      await apiFetch(`/api/tenants/${tenantId}/purge`, { method: 'DELETE' });
      toast.success(`"${businessName}" permanently deleted.`);
      await fetchTenants();
    } catch (err) {
      console.error('Purge failed:', err);
      toast.error(err.message || 'Permanent deletion failed.');
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
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Tenant Management</h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1">Approve, manage, and monitor registered businesses</p>
        </div>
        <button
          onClick={fetchTenants}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-blue-50 dark:bg-blue-900/50">
              <Building2 className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{totalCount}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">Total Tenants</p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/50">
              <Clock className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{pendingCount}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">Pending Approval</p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-green-50 dark:bg-green-900/50">
              <Wifi className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{activeCount}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">Active Tenants</p>
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
            className="w-full pl-10 pr-4 py-2.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none dark:bg-gray-700 dark:text-white"
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
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600'
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
        <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Tenant list */}
      {filtered.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Building2 className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-gray-400 text-sm">
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
              onPurge={() => purgeAccount(tenant.id, tenant.business_name, tenant.owner_email)}
              actionLoading={actionLoading === tenant.id}
              onRefresh={fetchTenants}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Individual tenant row ────────────────────────────────────────────────────

function TenantRow({ tenant, expanded, onToggle, onAction, onPurge, actionLoading, onRefresh }) {
  const { confirm, toast } = useModal();
  const cfg = STATUS_CONFIG[tenant.status] || STATUS_CONFIG.PENDING;
  const StatusIcon = cfg.icon;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Summary row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 p-4 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
      >
        {/* Status dot */}
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`}></div>

        {/* Business info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900 dark:text-white truncate">{tenant.business_name}</span>
            <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.color}`}>
              {cfg.label}
            </span>
            {tenant.demo_mode && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-400">
                Demo
              </span>
            )}
            {tenant.plan && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-400">
                {tenant.plan}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500 dark:text-gray-400">
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
        <div className="border-t border-gray-100 dark:border-gray-700 px-4 py-5 bg-gray-50/50 dark:bg-gray-700/50">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: details */}
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Details</h4>
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
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
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

          {/* ── Admin Provisioning: Vapi + Twilio assignment ──────────── */}
          <ProvisioningSection tenantId={tenant.id} tenant={tenant} onSaved={onRefresh} />

          {/* ── Tenant Usage Stats ─────────────────────────────────────── */}
          <TenantUsageStats tenantId={tenant.id} />

          {/* Greeting message */}
          {tenant.greeting_message && (
            <div className="mt-4 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Greeting Message</p>
              <p className="text-sm text-gray-700 dark:text-gray-300 italic">"{tenant.greeting_message}"</p>
            </div>
          )}

          {/* Location */}
          {(tenant.business_address || tenant.google_maps_url) && (
            <div className="mt-4 p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-2">
                <MapPin className="w-4 h-4 text-primary-500" />
                Clinic Location
              </h4>
              {tenant.business_address && (
                <p className="text-sm text-gray-700 dark:text-gray-300 mb-2">
                  {tenant.business_address}
                </p>
              )}
              {tenant.google_maps_url && (
                <a
                  href={tenant.google_maps_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Open in Google Maps
                </a>
              )}
            </div>
          )}

          {/* Profile Change History */}
          <TenantChangeHistory tenantId={tenant.id} />

          {/* Action buttons */}
          <div className="mt-5 pt-4 border-t border-gray-200 dark:border-gray-700 flex flex-wrap gap-2">
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
            {(tenant.status === 'SUSPENDED' || tenant.status === 'DEACTIVATED') && (
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
                onClick={async () => {
                  const ok = await confirm({
                    title: 'Deactivate Account?',
                    message: `Deactivate "${tenant.business_name}"? The account will be disabled but data will be preserved.`,
                    confirmText: 'Deactivate',
                    variant: 'danger',
                  });
                  if (ok) onAction('delete', 'DELETE');
                }}
              />
            )}
            <ActionButton
              icon={XCircle}
              label="Permanently Delete"
              color="red"
              loading={actionLoading}
              onClick={onPurge}
            />
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
      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 w-24 shrink-0 pt-0.5">{label}</span>
      <span
        className={`text-sm text-gray-800 dark:text-gray-200 break-all ${mono ? 'font-mono text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded' : ''}`}
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
        active ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400' : 'bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500'
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
      <span className="text-sm text-gray-700 dark:text-gray-300">{label}</span>
      <span className={`text-xs ${configured ? 'text-green-600 dark:text-green-400' : 'text-gray-400'}`}>
        {configured ? 'Connected' : 'Not configured'}
      </span>
    </div>
  );
}

function TenantChangeHistory({ tenantId }) {
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [show, setShow] = useState(false);

  async function loadChanges() {
    if (loaded) {
      setShow(!show);
      return;
    }
    setLoading(true);
    try {
      const data = await apiFetch(`/api/auth/profile-changes?tenant_id=${tenantId}`);
      setChanges(Array.isArray(data) ? data : []);
      setLoaded(true);
      setShow(true);
    } catch (err) {
      console.error('Failed to load changes:', err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-4">
      <button
        onClick={loadChanges}
        className="flex items-center gap-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
      >
        {loading ? (
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
        ) : (
          <History className="w-4 h-4" />
        )}
        {show ? 'Hide' : 'Show'} Change History
        {loaded && changes.length > 0 && (
          <span className="ml-1 px-1.5 py-0.5 bg-gray-100 dark:bg-gray-600 text-gray-500 dark:text-gray-400 rounded text-[10px]">
            {changes.length}
          </span>
        )}
      </button>

      {show && (
        <div className="mt-3 space-y-2">
          {changes.length === 0 ? (
            <p className="text-xs text-gray-400 dark:text-gray-500 py-2">No profile changes recorded.</p>
          ) : (
            changes.map((log) => (
              <div
                key={log.id}
                className="flex items-start gap-2.5 p-2.5 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 text-xs"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-primary-400 mt-1.5 shrink-0"></div>
                <div className="flex-1 min-w-0">
                  <p className="text-gray-900 dark:text-white font-medium">
                    {log.field_name === 'password' ? (
                      'Password changed'
                    ) : (
                      <>
                        <span className="text-gray-500 dark:text-gray-400">{log.field_name}:</span>{' '}
                        <span className="line-through text-gray-400 dark:text-gray-500">{log.old_value}</span>{' '}
                        <span className="text-primary-600 dark:text-primary-400">{log.new_value}</span>
                      </>
                    )}
                  </p>
                  <p className="text-gray-400 dark:text-gray-500 mt-0.5">
                    by {log.changed_by} · {log.created_at ? new Date(log.created_at).toLocaleString() : '—'}
                  </p>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Admin Provisioning Panel ────────────────────────────────────────────────
// Lets admin assign Vapi assistant ID, Vapi phone number ID, and Twilio
// phone number to a tenant. These are the per-tenant integration identifiers
// under the platform-managed (Option A) SaaS model.

function ProvisioningSection({ tenantId, tenant, onSaved }) {
  const { toast } = useModal();
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [fields, setFields] = useState({
    vapi_assistant_id: '',
    vapi_phone_number_id: '',
    twilio_phone_number: '',
  });

  // Load current values when opened
  useEffect(() => {
    if (show) {
      loadCurrentValues();
    }
  }, [show]);

  async function loadCurrentValues() {
    try {
      const data = await apiFetch(`/api/integrations/vapi/admin/${tenantId}`);
      setFields({
        vapi_assistant_id: data.vapi_assistant_id || '',
        vapi_phone_number_id: data.vapi_phone_number_id || '',
        twilio_phone_number: data.twilio_phone_number || '',
      });
    } catch (err) {
      // Fallback: use tenant data from list (may not have these fields)
      console.warn('Could not load provisioning details:', err);
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      await apiFetch(`/api/integrations/vapi/assign`, {
        method: 'POST',
        body: JSON.stringify({
          tenant_id: tenantId,
          vapi_assistant_id: fields.vapi_assistant_id.trim() || null,
          vapi_phone_number_id: fields.vapi_phone_number_id.trim() || null,
          twilio_phone_number: fields.twilio_phone_number.trim() || null,
        }),
      });
      toast.success('Integration settings saved.');
      if (onSaved) onSaved();
    } catch (err) {
      console.error('Failed to save provisioning:', err);
      toast.error(err.message || 'Failed to save integration settings.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4">
      <button
        onClick={() => setShow(!show)}
        className="flex items-center gap-2 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors"
      >
        <PhoneCall className="w-4 h-4" />
        {show ? 'Hide' : 'Manage'} Integration Provisioning
        {show ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>

      {show && (
        <div className="mt-3 p-4 bg-white dark:bg-gray-800 rounded-lg border border-indigo-200 dark:border-indigo-800 space-y-4">
          <div>
            <p className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider mb-3">
              Platform Integration Assignment
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
              Assign Vapi and Twilio resources to this tenant. These are managed under the platform's global accounts.
            </p>
          </div>

          {/* Vapi Assistant ID */}
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              <Phone className="w-3.5 h-3.5 inline mr-1" />
              Vapi Assistant ID
            </label>
            <input
              type="text"
              value={fields.vapi_assistant_id}
              onChange={(e) => setFields((f) => ({ ...f, vapi_assistant_id: e.target.value }))}
              placeholder="e.g. asst_abc123..."
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none dark:bg-gray-700 dark:text-white font-mono"
            />
            <p className="text-[11px] text-gray-400 mt-1">The Vapi assistant provisioned for this tenant's voice agent.</p>
          </div>

          {/* Vapi Phone Number ID */}
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              <PhoneCall className="w-3.5 h-3.5 inline mr-1" />
              Vapi Phone Number ID
            </label>
            <input
              type="text"
              value={fields.vapi_phone_number_id}
              onChange={(e) => setFields((f) => ({ ...f, vapi_phone_number_id: e.target.value }))}
              placeholder="e.g. phn_xyz789..."
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none dark:bg-gray-700 dark:text-white font-mono"
            />
            <p className="text-[11px] text-gray-400 mt-1">Vapi phone number ID assigned to this tenant (from the platform's Vapi account).</p>
          </div>

          {/* Twilio Phone Number */}
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              <MessageSquare className="w-3.5 h-3.5 inline mr-1" />
              Twilio Phone Number
            </label>
            <input
              type="text"
              value={fields.twilio_phone_number}
              onChange={(e) => setFields((f) => ({ ...f, twilio_phone_number: e.target.value }))}
              placeholder="e.g. +14155551234"
              className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none dark:bg-gray-700 dark:text-white font-mono"
            />
            <p className="text-[11px] text-gray-400 mt-1">
              Twilio SMS number from the platform account. Buy numbers in the Twilio Console, then assign here.
            </p>
          </div>

          {/* Save button */}
          <div className="pt-2 flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
            >
              {saving ? (
                <div className="animate-spin rounded-full h-3.5 w-3.5 border-b-2 border-white"></div>
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              Save Integration Settings
            </button>
            <button
              onClick={() => setShow(false)}
              className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tenant Usage Stats (inline) ─────────────────────────────────────────────

function TenantUsageStats({ tenantId }) {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(false);

  async function loadUsage() {
    if (usage) {
      setShow(!show);
      return;
    }
    setLoading(true);
    try {
      const data = await apiFetch(`/api/integrations/vapi/admin/${tenantId}/usage`);
      setUsage(data);
      setShow(true);
    } catch (err) {
      console.error('Failed to load usage:', err);
      setShow(true);
      setUsage(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-4">
      <button
        onClick={loadUsage}
        className="flex items-center gap-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
      >
        {loading ? (
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
        ) : (
          <BarChart3 className="w-4 h-4" />
        )}
        {show ? 'Hide' : 'Show'} Usage Stats
      </button>

      {show && (
        <div className="mt-3 p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          {!usage ? (
            <p className="text-xs text-gray-400">Could not load usage data for this tenant.</p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                <span>Plan: <strong className="text-gray-900 dark:text-white">{usage.plan || '—'}</strong></span>
                {usage.period_start && (
                  <span>Period started: {new Date(usage.period_start).toLocaleDateString()}</span>
                )}
              </div>

              {/* Call minutes bar */}
              <div>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-600 dark:text-gray-400">Call Minutes</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {usage.call_minutes_used?.toFixed(1) || '0'} / {usage.call_minutes_limit ?? '∞'}
                  </span>
                </div>
                <MiniUsageBar used={usage.call_minutes_used || 0} limit={usage.call_minutes_limit} />
              </div>

              {/* SMS bar */}
              <div>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-600 dark:text-gray-400">SMS Sent</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {usage.sms_sent || 0} / {usage.sms_limit ?? '∞'}
                  </span>
                </div>
                <MiniUsageBar used={usage.sms_sent || 0} limit={usage.sms_limit} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MiniUsageBar({ used, limit }) {
  const pct = limit ? Math.min((used / limit) * 100, 100) : 0;
  const color = pct >= 95 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-green-500';
  return (
    <div className="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function ActionButton({ icon: Icon, label, color, loading, onClick }) {
  const colorMap = {
    green: 'bg-green-50 text-green-700 hover:bg-green-100 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50 dark:border-green-800',
    amber: 'bg-amber-50 text-amber-700 hover:bg-amber-100 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:hover:bg-amber-900/50 dark:border-amber-800',
    blue: 'bg-blue-50 text-blue-700 hover:bg-blue-100 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50 dark:border-blue-800',
    red: 'bg-red-50 text-red-700 hover:bg-red-100 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50 dark:border-red-800',
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
