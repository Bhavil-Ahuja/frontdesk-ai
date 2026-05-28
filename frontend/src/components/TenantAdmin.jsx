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
  ChevronDown,
  ChevronUp,
  ExternalLink,
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
  HelpCircle,
  Loader2,
  Send,
  Users,
  Settings2,
  ToggleLeft,
  ToggleRight,
  Info,
  Zap,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useModal } from '../contexts/ModalContext';

// ── Constants ───────────────────────────────────────────────────────────────

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

const TOP_TABS = [
  { key: 'tenants', label: 'Tenants', icon: Building2 },
  { key: 'tickets', label: 'Support Tickets', icon: HelpCircle },
];

const TENANT_TABS = [
  { key: 'overview', label: 'Overview', icon: Info },
  { key: 'integrations', label: 'Integrations & Flags', icon: Zap },
  { key: 'usage', label: 'Usage & History', icon: BarChart3 },
];

// ── Main Component ──────────────────────────────────────────────────────────

export default function TenantAdmin() {
  const [activeTopTab, setActiveTopTab] = useState('tenants');
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const [error, setError] = useState(null);
  const { toast, confirm, prompt } = useModal();

  // Support tickets state
  const [ticketStats, setTicketStats] = useState(null);
  const [adminTickets, setAdminTickets] = useState([]);
  const [ticketsLoading, setTicketsLoading] = useState(false);
  const [ticketStatusFilter, setTicketStatusFilter] = useState('OPEN');
  const [updatingTicketId, setUpdatingTicketId] = useState(null);
  const [expandedTicketId, setExpandedTicketId] = useState(null);
  const [replyText, setReplyText] = useState('');
  const [sendingReply, setSendingReply] = useState(false);

  useEffect(() => {
    fetchTenants();
    fetchTicketStats();
  }, [statusFilter]);

  // ── Data fetching ──

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

  async function fetchTicketStats() {
    try {
      const stats = await apiFetch('/api/admin/support/tickets/stats');
      setTicketStats(stats);
    } catch (err) {
      console.error('Failed to fetch ticket stats:', err);
    }
  }

  async function fetchAdminTickets(status = 'OPEN') {
    setTicketsLoading(true);
    try {
      const params = status !== 'ALL' ? `?status=${status}` : '';
      const data = await apiFetch(`/api/admin/support/tickets${params}`);
      setAdminTickets(data.tickets || []);
    } catch (err) {
      console.error('Failed to fetch admin tickets:', err);
    } finally {
      setTicketsLoading(false);
    }
  }

  async function updateTicketStatus(ticketId, newStatus) {
    setUpdatingTicketId(ticketId);
    try {
      await apiFetch(`/api/admin/support/tickets/${ticketId}`, {
        method: 'PATCH',
        body: { status: newStatus },
      });
      fetchAdminTickets(ticketStatusFilter);
      fetchTicketStats();
      toast.success('Ticket updated');
    } catch (err) {
      toast.error('Failed to update ticket');
    } finally {
      setUpdatingTicketId(null);
    }
  }

  async function handleExpandTicket(ticketId) {
    if (expandedTicketId === ticketId) {
      setExpandedTicketId(null);
      setReplyText('');
      return;
    }
    setExpandedTicketId(ticketId);
    setReplyText('');
    try {
      const detail = await apiFetch(`/api/admin/support/tickets/${ticketId}`);
      setAdminTickets((prev) =>
        prev.map((t) => (t.id === ticketId ? { ...t, ...detail } : t))
      );
    } catch (err) {
      console.error('Failed to fetch ticket detail:', err);
    }
  }

  async function sendAdminReply(ticketId) {
    if (!replyText.trim()) return;
    setSendingReply(true);
    try {
      const updated = await apiFetch(`/api/admin/support/tickets/${ticketId}/messages`, {
        method: 'POST',
        body: { body: replyText.trim() },
      });
      setAdminTickets((prev) =>
        prev.map((t) => (t.id === ticketId ? { ...t, ...updated } : t))
      );
      setReplyText('');
      fetchTicketStats();
      toast.success('Reply sent');
    } catch (err) {
      toast.error('Failed to send reply');
    } finally {
      setSendingReply(false);
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
    const first = await confirm({
      title: 'Permanently Delete Account?',
      message: `This will permanently delete "${businessName}" (${email}) and ALL associated data — appointments, patients, calls, SMS messages.\n\nThis action is IRREVERSIBLE.`,
      confirmText: 'Continue',
      variant: 'danger',
    });
    if (!first) return;

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

  // Client-side search filter
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

  const pendingCount = tenants.filter((t) => t.status === 'PENDING').length;
  const activeCount = tenants.filter((t) => t.status === 'ACTIVE').length;
  const totalCount = tenants.length;
  const openTicketCount = (ticketStats?.OPEN || 0) + (ticketStats?.REOPENED || 0);

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
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Platform Admin</h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1">Manage tenants, support tickets, and platform settings</p>
        </div>
        <button
          onClick={() => { fetchTenants(); fetchTicketStats(); }}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ── Top-level tab bar ─────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-gray-200 dark:border-gray-700">
        {TOP_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => {
              setActiveTopTab(key);
              if (key === 'tickets' && adminTickets.length === 0) fetchAdminTickets(ticketStatusFilter);
            }}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTopTab === key
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
            {key === 'tenants' && pendingCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-400 rounded-full text-[10px] font-bold">
                {pendingCount}
              </span>
            )}
            {key === 'tickets' && openTicketCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400 rounded-full text-[10px] font-bold">
                {openTicketCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab Content ───────────────────────────────────────────────── */}
      {activeTopTab === 'tenants' && (
        <TenantsTab
          tenants={filtered}
          totalCount={totalCount}
          pendingCount={pendingCount}
          activeCount={activeCount}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          expandedId={expandedId}
          setExpandedId={setExpandedId}
          actionLoading={actionLoading}
          error={error}
          performAction={performAction}
          purgeAccount={purgeAccount}
          onRefresh={fetchTenants}
        />
      )}

      {activeTopTab === 'tickets' && (
        <TicketsTab
          tickets={adminTickets}
          ticketsLoading={ticketsLoading}
          ticketStatusFilter={ticketStatusFilter}
          setTicketStatusFilter={(s) => { setTicketStatusFilter(s); fetchAdminTickets(s); }}
          ticketStats={ticketStats}
          expandedTicketId={expandedTicketId}
          handleExpandTicket={handleExpandTicket}
          updateTicketStatus={updateTicketStatus}
          updatingTicketId={updatingTicketId}
          replyText={replyText}
          setReplyText={setReplyText}
          sendAdminReply={sendAdminReply}
          sendingReply={sendingReply}
        />
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TENANTS TAB
// ═══════════════════════════════════════════════════════════════════════════

function TenantsTab({
  tenants, totalCount, pendingCount, activeCount,
  statusFilter, setStatusFilter, searchQuery, setSearchQuery,
  expandedId, setExpandedId, actionLoading, error,
  performAction, purgeAccount, onRefresh,
}) {
  return (
    <div className="space-y-5">
      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard icon={Building2} iconBg="bg-blue-50 dark:bg-blue-900/50" iconColor="text-blue-600" value={totalCount} label="Total Tenants" />
        <StatCard icon={Clock} iconBg="bg-amber-50 dark:bg-amber-900/50" iconColor="text-amber-600" value={pendingCount} label="Pending Approval" />
        <StatCard icon={Wifi} iconBg="bg-green-50 dark:bg-green-900/50" iconColor="text-green-600" value={activeCount} label="Active Tenants" />
      </div>

      {/* Search + status filters */}
      <div className="flex flex-col sm:flex-row gap-3">
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
                <span className="ml-1 bg-white/30 px-1.5 py-0.5 rounded-full text-[10px]">{pendingCount}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Tenant list */}
      {tenants.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Building2 className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            {searchQuery ? 'No tenants match your search.' : statusFilter !== 'ALL' ? `No ${STATUS_CONFIG[statusFilter]?.label?.toLowerCase()} tenants.` : 'No tenants registered yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {tenants.map((tenant) => (
            <TenantRow
              key={tenant.id}
              tenant={tenant}
              expanded={expandedId === tenant.id}
              onToggle={() => setExpandedId(expandedId === tenant.id ? null : tenant.id)}
              onAction={(action, method) => performAction(tenant.id, action, method)}
              onPurge={() => purgeAccount(tenant.id, tenant.business_name, tenant.owner_email)}
              actionLoading={actionLoading === tenant.id}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// SUPPORT TICKETS TAB
// ═══════════════════════════════════════════════════════════════════════════

function TicketsTab({
  tickets, ticketsLoading, ticketStatusFilter, setTicketStatusFilter,
  ticketStats, expandedTicketId, handleExpandTicket, updateTicketStatus,
  updatingTicketId, replyText, setReplyText, sendAdminReply, sendingReply,
}) {
  return (
    <div className="space-y-4">
      {/* Status filter bar */}
      <div className="flex items-center gap-1 flex-wrap">
        {['OPEN', 'REOPENED', 'IN_PROGRESS', 'RESOLVED', 'ALL'].map((s) => (
          <button
            key={s}
            onClick={() => setTicketStatusFilter(s)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              ticketStatusFilter === s
                ? 'bg-violet-500 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600'
            }`}
          >
            {s === 'IN_PROGRESS' ? 'In Progress' : s === 'ALL' ? 'All' : s.charAt(0) + s.slice(1).toLowerCase()}
            {s !== 'ALL' && ticketStats?.[s] > 0 && (
              <span className="ml-1 opacity-70">({ticketStats[s]})</span>
            )}
          </button>
        ))}
      </div>

      {/* Ticket list */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {ticketsLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-violet-500" />
            </div>
          ) : tickets.length === 0 ? (
            <div className="text-center py-12">
              <HelpCircle className="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
              <p className="text-gray-400 text-sm">No tickets in this category</p>
            </div>
          ) : (
            tickets.map((ticket) => (
              <TicketRow
                key={ticket.id}
                ticket={ticket}
                isExpanded={expandedTicketId === ticket.id}
                onToggle={() => handleExpandTicket(ticket.id)}
                onStatusChange={updateTicketStatus}
                updatingTicketId={updatingTicketId}
                replyText={expandedTicketId === ticket.id ? replyText : ''}
                setReplyText={setReplyText}
                sendReply={() => sendAdminReply(ticket.id)}
                sendingReply={sendingReply}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function TicketRow({
  ticket, isExpanded, onToggle, onStatusChange, updatingTicketId,
  replyText, setReplyText, sendReply, sendingReply,
}) {
  const messages = ticket.messages || [];
  const statusColor =
    ticket.status === 'OPEN' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400' :
    ticket.status === 'REOPENED' ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400' :
    ticket.status === 'IN_PROGRESS' ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400' :
    ticket.status === 'RESOLVED' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400' :
    'bg-gray-100 dark:bg-gray-700 text-gray-500';
  const statusLabel =
    ticket.status === 'IN_PROGRESS' ? 'In Progress' :
    ticket.status === 'REOPENED' ? 'Reopened' :
    ticket.status.charAt(0) + ticket.status.slice(1).toLowerCase();
  const canReply = !['CLOSED'].includes(ticket.status);

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="w-full p-4 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm text-gray-900 dark:text-white">{ticket.subject}</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusColor}`}>{statusLabel}</span>
              <span className={`text-[10px] font-medium ${
                ticket.priority === 'URGENT' ? 'text-red-500' : ticket.priority === 'HIGH' ? 'text-orange-500' : 'text-gray-400'
              }`}>{ticket.priority}</span>
              {(ticket.message_count > 0) && (
                <span className="inline-flex items-center gap-0.5 text-[10px] text-gray-400">
                  <MessageSquare className="w-2.5 h-2.5" /> {ticket.message_count}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {ticket.tenant_name || ticket.tenant_slug || 'Unknown'} · {ticket.category?.replace('_', ' ')} · {new Date(ticket.created_at).toLocaleDateString()}
            </p>
            {!isExpanded && (
              <p className="text-xs text-gray-600 dark:text-gray-400 mt-1 line-clamp-1">{ticket.body}</p>
            )}
          </div>
          {isExpanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
        </div>
      </button>

      {isExpanded && (
        <div className="bg-gray-50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-700 px-4 pb-4">
          {/* Description */}
          <div className="pt-3 pb-2">
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1">Description</p>
            <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{ticket.body}</p>
          </div>

          {/* Conversation */}
          {messages.length > 0 && (
            <div className="pt-2 pb-2">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-2 flex items-center gap-1">
                <MessageSquare className="w-3 h-3" /> Conversation ({messages.length})
              </p>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {messages.map((msg) => {
                  const isAdmin = msg.sender_type === 'ADMIN';
                  return (
                    <div key={msg.id} className={`flex ${isAdmin ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[80%] rounded-2xl px-3 py-2 ${
                        isAdmin
                          ? 'bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-br-md'
                          : 'bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-bl-md'
                      }`}>
                        <p className={`text-[10px] font-medium mb-0.5 ${isAdmin ? 'text-violet-600 dark:text-violet-400' : 'text-gray-500 dark:text-gray-400'}`}>
                          {isAdmin ? '🛡 ' : ''}{msg.sender_name}
                        </p>
                        <p className="text-xs text-gray-800 dark:text-gray-200 whitespace-pre-wrap">{msg.body}</p>
                        <p className="text-[9px] text-gray-400 mt-1">
                          {new Date(msg.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true })}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Reply input */}
          {canReply && (
            <div className="flex gap-2 pt-2">
              <input
                type="text"
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendReply(); } }}
                placeholder="Type a reply..."
                className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              />
              <button
                onClick={sendReply}
                disabled={sendingReply || !replyText.trim()}
                className="px-3 py-2 bg-violet-500 text-white rounded-lg text-sm font-medium hover:bg-violet-600 disabled:opacity-50 transition-colors"
              >
                {sendingReply ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-3">
            {(ticket.status === 'OPEN' || ticket.status === 'REOPENED') && (
              <ActionButton icon={Clock} label="Start Working" color="amber" loading={updatingTicketId === ticket.id} onClick={() => onStatusChange(ticket.id, 'IN_PROGRESS')} />
            )}
            {(ticket.status === 'OPEN' || ticket.status === 'IN_PROGRESS' || ticket.status === 'REOPENED') && (
              <ActionButton icon={CheckCircle} label="Resolve" color="green" loading={updatingTicketId === ticket.id} onClick={() => onStatusChange(ticket.id, 'RESOLVED')} />
            )}
            {ticket.status === 'RESOLVED' && (
              <ActionButton icon={XCircle} label="Close" color="gray" loading={updatingTicketId === ticket.id} onClick={() => onStatusChange(ticket.id, 'CLOSED')} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TENANT ROW (expandable with inner tabs)
// ═══════════════════════════════════════════════════════════════════════════

function TenantRow({ tenant, expanded, onToggle, onAction, onPurge, actionLoading, onRefresh }) {
  const { confirm, toast } = useModal();
  const cfg = STATUS_CONFIG[tenant.status] || STATUS_CONFIG.PENDING;
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Summary row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 p-4 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
      >
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`}></div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900 dark:text-white truncate">{tenant.business_name}</span>
            <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.color}`}>{cfg.label}</span>
            {tenant.demo_mode && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-400">Demo</span>
            )}
            {tenant.plan && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-400">{tenant.plan}</span>
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
          <IntegrationBadge label="Vapi" active={tenant.vapi_configured} enabled={tenant.feature_vapi_enabled !== false} />
          <IntegrationBadge label="GCal" active={tenant.google_calendar_connected} />
          <IntegrationBadge label="Twilio" active={tenant.twilio_configured} enabled={tenant.feature_twilio_enabled !== false} />
        </div>

        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400 shrink-0" /> : <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />}
      </button>

      {/* Expanded detail with inner tabs */}
      {expanded && (
        <div className="border-t border-gray-100 dark:border-gray-700">
          {/* Inner tab bar */}
          <div className="flex items-center gap-0 border-b border-gray-100 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-700/30 px-4">
            {TENANT_TABS.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                  activeTab === key
                    ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="px-4 py-5 bg-gray-50/50 dark:bg-gray-700/50">
            {activeTab === 'overview' && (
              <OverviewTab tenant={tenant} />
            )}
            {activeTab === 'integrations' && (
              <IntegrationsTab tenantId={tenant.id} tenant={tenant} onRefresh={onRefresh} />
            )}
            {activeTab === 'usage' && (
              <UsageHistoryTab tenantId={tenant.id} />
            )}

            {/* Action buttons — always visible */}
            <div className="mt-5 pt-4 border-t border-gray-200 dark:border-gray-700 flex flex-wrap gap-2">
              {tenant.status === 'PENDING' && (
                <ActionButton icon={CheckCircle} label="Approve" color="green" loading={actionLoading} onClick={() => onAction('approve')} />
              )}
              {tenant.status === 'ACTIVE' && (
                <ActionButton icon={PauseCircle} label="Suspend" color="amber" loading={actionLoading} onClick={() => onAction('suspend')} />
              )}
              {(tenant.status === 'SUSPENDED' || tenant.status === 'DEACTIVATED') && (
                <ActionButton icon={PlayCircle} label="Reactivate" color="blue" loading={actionLoading} onClick={() => onAction('reactivate')} />
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
              <ActionButton icon={XCircle} label="Permanently Delete" color="red" loading={actionLoading} onClick={onPurge} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TENANT INNER TABS
// ═══════════════════════════════════════════════════════════════════════════

// ── Overview Tab ──────────────────────────────────────────────────────────

function OverviewTab({ tenant }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Left: Business details */}
        <div className="space-y-3">
          <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Business Details</h4>
          <DetailRow label="ID" value={tenant.id} mono />
          <DetailRow label="Slug" value={tenant.slug} mono />
          <DetailRow label="Business Type" value={tenant.business_type || '—'} />
          <DetailRow label="Timezone" value={tenant.timezone} />
          <DetailRow label="Plan" value={tenant.plan || '—'} />
          <DetailRow label="Agent Name" value={tenant.agent_name || '—'} />
          <DetailRow label="Created" value={tenant.created_at ? new Date(tenant.created_at).toLocaleString() : '—'} />
          <DetailRow label="Updated" value={tenant.updated_at ? new Date(tenant.updated_at).toLocaleString() : '—'} />
        </div>

        {/* Right: Owner info */}
        <div className="space-y-3">
          <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Owner</h4>
          <DetailRow label="Name" value={tenant.owner_name} />
          <DetailRow label="Email" value={tenant.owner_email} />
          <DetailRow label="Phone" value={tenant.owner_phone || '—'} />
        </div>
      </div>

      {/* Greeting message */}
      {tenant.greeting_message && (
        <div className="p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Greeting Message</p>
          <p className="text-sm text-gray-700 dark:text-gray-300 italic">"{tenant.greeting_message}"</p>
        </div>
      )}

      {/* Location */}
      {(tenant.business_address || tenant.google_maps_url) && (
        <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <h4 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-2">
            <MapPin className="w-4 h-4 text-primary-500" />
            Clinic Location
          </h4>
          {tenant.business_address && (
            <p className="text-sm text-gray-700 dark:text-gray-300 mb-2">{tenant.business_address}</p>
          )}
          {tenant.google_maps_url && (
            <a href={tenant.google_maps_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300">
              <ExternalLink className="w-3.5 h-3.5" />
              Open in Google Maps
            </a>
          )}
        </div>
      )}
    </div>
  );
}

// ── Integrations & Flags Tab ─────────────────────────────────────────────

function IntegrationsTab({ tenantId, tenant, onRefresh }) {
  const { toast } = useModal();
  const [saving, setSaving] = useState(false);
  const [fields, setFields] = useState({
    vapi_assistant_id: '',
    vapi_phone_number_id: '',
    twilio_phone_number: '',
    feature_vapi_enabled: tenant.feature_vapi_enabled !== false,
    feature_twilio_enabled: tenant.feature_twilio_enabled !== false,
  });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!loaded) loadCurrentValues();
  }, []);

  async function loadCurrentValues() {
    try {
      const data = await apiFetch(`/api/integrations/vapi/admin/${tenantId}`);
      setFields({
        vapi_assistant_id: data.vapi_assistant_id || '',
        vapi_phone_number_id: data.vapi_phone_number_id || '',
        twilio_phone_number: data.twilio_phone_number || '',
        feature_vapi_enabled: data.feature_vapi_enabled !== false,
        feature_twilio_enabled: data.feature_twilio_enabled !== false,
      });
    } catch (err) {
      // Use tenant-level data as fallback
      setFields((f) => ({
        ...f,
        feature_vapi_enabled: tenant.feature_vapi_enabled !== false,
        feature_twilio_enabled: tenant.feature_twilio_enabled !== false,
      }));
    }
    setLoaded(true);
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
          feature_vapi_enabled: fields.feature_vapi_enabled,
          feature_twilio_enabled: fields.feature_twilio_enabled,
        }),
      });
      toast.success('Integration settings saved.');
      if (onRefresh) onRefresh();
    } catch (err) {
      console.error('Failed to save:', err);
      toast.error(err.message || 'Failed to save integration settings.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Feature Flags section */}
      <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
          <Settings2 className="w-3.5 h-3.5" />
          Feature Flags
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
          Toggle features on/off for this tenant. When disabled, the feature is completely hidden and non-functional — even if API keys are configured.
        </p>
        <div className="space-y-3">
          <FeatureToggle
            label="Voice Agent (Vapi)"
            description="AI phone receptionist — inbound call handling, appointment booking by voice"
            enabled={fields.feature_vapi_enabled}
            onChange={(v) => setFields((f) => ({ ...f, feature_vapi_enabled: v }))}
          />
          <FeatureToggle
            label="SMS (Twilio)"
            description="Appointment confirmations, reminders, waitlist notifications via text"
            enabled={fields.feature_twilio_enabled}
            onChange={(v) => setFields((f) => ({ ...f, feature_twilio_enabled: v }))}
          />
        </div>
      </div>

      {/* Connection status */}
      <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Connection Status</h4>
        <div className="space-y-2">
          <IntegrationStatus label="Vapi" configured={tenant.vapi_configured} enabled={fields.feature_vapi_enabled} />
          <IntegrationStatus
            label={`Google Calendar${tenant.google_calendar_email ? ` (${tenant.google_calendar_email})` : ''}`}
            configured={tenant.google_calendar_connected}
          />
          <IntegrationStatus label="Twilio" configured={tenant.twilio_configured} enabled={fields.feature_twilio_enabled} />
        </div>
      </div>

      {/* Provisioning fields */}
      <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-indigo-200 dark:border-indigo-800">
        <h4 className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <PhoneCall className="w-3.5 h-3.5" />
          Integration Assignment
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
          Assign Vapi and Twilio resources from the platform's global accounts.
        </p>

        <div className="space-y-4">
          <ProvisioningField
            icon={Phone}
            label="Vapi Assistant ID"
            value={fields.vapi_assistant_id}
            onChange={(v) => setFields((f) => ({ ...f, vapi_assistant_id: v }))}
            placeholder="e.g. asst_abc123..."
            hint="The Vapi assistant provisioned for this tenant's voice agent."
          />
          <ProvisioningField
            icon={PhoneCall}
            label="Vapi Phone Number ID"
            value={fields.vapi_phone_number_id}
            onChange={(v) => setFields((f) => ({ ...f, vapi_phone_number_id: v }))}
            placeholder="e.g. phn_xyz789..."
            hint="Vapi phone number ID assigned to this tenant."
          />
          <ProvisioningField
            icon={MessageSquare}
            label="Twilio Phone Number"
            value={fields.twilio_phone_number}
            onChange={(v) => setFields((f) => ({ ...f, twilio_phone_number: v }))}
            placeholder="e.g. +14155551234"
            hint="Twilio SMS number from the platform account."
          />
        </div>

        <div className="pt-4 flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save All Settings
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Usage & History Tab ──────────────────────────────────────────────────

function UsageHistoryTab({ tenantId }) {
  return (
    <div className="space-y-5">
      <TenantUsageStats tenantId={tenantId} />
      <TenantChangeHistory tenantId={tenantId} />
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// SHARED SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

function StatCard({ icon: Icon, iconBg, iconColor, value, label }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-center gap-3">
        <div className={`p-2.5 rounded-lg ${iconBg}`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
        <div>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
          <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
        </div>
      </div>
    </div>
  );
}

function DetailRow({ label, value, mono }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 w-24 shrink-0 pt-0.5">{label}</span>
      <span className={`text-sm text-gray-800 dark:text-gray-200 break-all ${mono ? 'font-mono text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded' : ''}`}>
        {value}
      </span>
    </div>
  );
}

function IntegrationBadge({ label, active, enabled = true }) {
  if (!enabled) {
    return (
      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500 line-through">
        {label}
      </span>
    );
  }
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
      active ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400' : 'bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500'
    }`}>
      {label}
    </span>
  );
}

function IntegrationStatus({ label, configured, enabled = true }) {
  return (
    <div className="flex items-center gap-2">
      <div className={`w-2 h-2 rounded-full ${
        !enabled ? 'bg-gray-300 dark:bg-gray-600' : configured ? 'bg-green-400' : 'bg-gray-300'
      }`}></div>
      <span className={`text-sm ${!enabled ? 'text-gray-400 line-through' : 'text-gray-700 dark:text-gray-300'}`}>{label}</span>
      <span className={`text-xs ${
        !enabled ? 'text-gray-400 dark:text-gray-500' : configured ? 'text-green-600 dark:text-green-400' : 'text-gray-400'
      }`}>
        {!enabled ? 'Disabled' : configured ? 'Connected' : 'Not configured'}
      </span>
    </div>
  );
}

function FeatureToggle({ label, description, enabled, onChange }) {
  return (
    <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
      <div>
        <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
      </div>
      <button
        onClick={() => onChange(!enabled)}
        className={`relative shrink-0 ml-4 w-11 h-6 rounded-full transition-colors ${
          enabled ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'
        }`}
      >
        <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
          enabled ? 'translate-x-5' : 'translate-x-0'
        }`} />
      </button>
    </div>
  );
}

function ProvisioningField({ icon: Icon, label, value, onChange, placeholder, hint }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
        <Icon className="w-3.5 h-3.5 inline mr-1" />
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none dark:bg-gray-700 dark:text-white font-mono"
      />
      {hint && <p className="text-[11px] text-gray-400 mt-1">{hint}</p>}
    </div>
  );
}

function TenantChangeHistory({ tenantId }) {
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!loaded) loadChanges();
  }, []);

  async function loadChanges() {
    setLoading(true);
    try {
      const data = await apiFetch(`/api/auth/profile-changes?tenant_id=${tenantId}`);
      setChanges(Array.isArray(data) ? data : []);
      setLoaded(true);
    } catch (err) {
      console.error('Failed to load changes:', err);
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <History className="w-3.5 h-3.5" />
        Change History
        {loaded && changes.length > 0 && (
          <span className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-600 text-gray-500 dark:text-gray-400 rounded text-[10px]">{changes.length}</span>
        )}
      </h4>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
        </div>
      ) : changes.length === 0 ? (
        <p className="text-xs text-gray-400 dark:text-gray-500 py-2">No profile changes recorded.</p>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {changes.map((log) => (
            <div key={log.id} className="flex items-start gap-2.5 p-2.5 bg-gray-50 dark:bg-gray-700/50 rounded-lg text-xs">
              <div className="w-1.5 h-1.5 rounded-full bg-primary-400 mt-1.5 shrink-0"></div>
              <div className="flex-1 min-w-0">
                <p className="text-gray-900 dark:text-white font-medium">
                  {log.field_name === 'password' ? 'Password changed' : (
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
          ))}
        </div>
      )}
    </div>
  );
}

function TenantUsageStats({ tenantId }) {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!loaded) loadUsage();
  }, []);

  async function loadUsage() {
    setLoading(true);
    try {
      const data = await apiFetch(`/api/integrations/vapi/admin/${tenantId}/usage`);
      setUsage(data);
    } catch (err) {
      console.error('Failed to load usage:', err);
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }

  return (
    <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <BarChart3 className="w-3.5 h-3.5" />
        Usage Stats
      </h4>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
        </div>
      ) : !usage ? (
        <p className="text-xs text-gray-400 py-2">Could not load usage data.</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>Plan: <strong className="text-gray-900 dark:text-white">{usage.plan || '—'}</strong></span>
            {usage.period_start && (
              <span>Period started: {new Date(usage.period_start).toLocaleDateString()}</span>
            )}
          </div>
          <UsageBar label="Call Minutes" used={usage.call_minutes_used?.toFixed(1) || '0'} limit={usage.call_minutes_limit} raw={usage.call_minutes_used || 0} />
          <UsageBar label="SMS Sent" used={usage.sms_sent || 0} limit={usage.sms_limit} raw={usage.sms_sent || 0} />
        </div>
      )}
    </div>
  );
}

function UsageBar({ label, used, limit, raw }) {
  const pct = limit ? Math.min((raw / limit) * 100, 100) : 0;
  const color = pct >= 95 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-green-500';
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-gray-600 dark:text-gray-400">{label}</span>
        <span className="font-medium text-gray-900 dark:text-white">{used} / {limit ?? '∞'}</span>
      </div>
      <div className="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ActionButton({ icon: Icon, label, color, loading, onClick }) {
  const colorMap = {
    green: 'bg-green-50 text-green-700 hover:bg-green-100 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50 dark:border-green-800',
    amber: 'bg-amber-50 text-amber-700 hover:bg-amber-100 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:hover:bg-amber-900/50 dark:border-amber-800',
    blue: 'bg-blue-50 text-blue-700 hover:bg-blue-100 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50 dark:border-blue-800',
    red: 'bg-red-50 text-red-700 hover:bg-red-100 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50 dark:border-red-800',
    gray: 'bg-gray-100 text-gray-600 hover:bg-gray-200 border-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600 dark:border-gray-600',
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
