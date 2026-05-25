import React, { useState, useEffect } from 'react';
import {
  Phone,
  ChevronDown,
  ChevronUp,
  Download,
  Filter,
  Search,
} from 'lucide-react';
import { apiFetch, getToken } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatDateTime } from '../lib/timezone';

const OUTCOME_STYLES = {
  BOOKED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INQUIRY: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  ESCALATED: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  CANCELLED: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  ABANDONED: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
};

export default function CallLogs() {
  const { user } = useAuth();
  const tz = user?.timezone || 'America/Chicago';
  const [calls, setCalls] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [expandedId, setExpandedId] = useState(null);
  const [expandedCall, setExpandedCall] = useState(null);
  const [outcomeFilter, setOutcomeFilter] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCalls();
  }, [page, outcomeFilter]);

  async function fetchCalls() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: 15 });
      if (outcomeFilter) params.set('outcome', outcomeFilter);
      const data = await apiFetch(`/api/calls?${params}`);
      setCalls(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (err) {
      console.error('Failed to fetch calls:', err);
    } finally {
      setLoading(false);
    }
  }

  async function toggleExpand(callId) {
    if (expandedId === callId) {
      setExpandedId(null);
      setExpandedCall(null);
      return;
    }
    try {
      const data = await apiFetch(`/api/calls/${callId}`);
      setExpandedCall(data);
      setExpandedId(callId);
    } catch (err) {
      console.error('Failed to fetch call detail:', err);
    }
  }

  async function exportCsv() {
    // Token-aware CSV download via blob
    try {
      const token = getToken();
      const res = await fetch('/api/calls/export', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `calls-export-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
    }
  }

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Call Logs</h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1">{total} total calls</p>
        </div>
        <button
          onClick={exportCsv}
          className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
        >
          <Download className="w-4 h-4" />
          Export CSV
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          <Filter className="w-4 h-4" />
          Filter:
        </div>
        <select
          value={outcomeFilter}
          onChange={(e) => { setOutcomeFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 border border-gray-200 dark:border-gray-700 rounded-lg text-sm bg-white dark:bg-gray-800 dark:text-gray-200 focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
        >
          <option value="">All Outcomes</option>
          <option value="BOOKED">Booked</option>
          <option value="INQUIRY">Inquiry</option>
          <option value="ESCALATED">Escalated</option>
          <option value="CANCELLED">Cancelled</option>
          <option value="ABANDONED">Abandoned</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Caller
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Date & Time
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Duration
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Outcome
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-gray-400">
                  Loading...
                </td>
              </tr>
            ) : calls.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-gray-400">
                  No calls found
                </td>
              </tr>
            ) : (
              calls.map((call) => (
                <React.Fragment key={call.id}>
                  <tr className="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors cursor-pointer" onClick={() => toggleExpand(call.id)}>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Phone className="w-4 h-4 text-gray-400" />
                        <span className="text-sm font-medium text-gray-900 dark:text-white">
                          {call.caller_number || 'Unknown'}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">
                      {call.started_at
                        ? formatDateTime(call.started_at, tz)
                        : '—'}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">
                      {call.duration_seconds
                        ? formatDuration(call.duration_seconds)
                        : '—'}
                    </td>
                    <td className="px-6 py-4">
                      {call.outcome ? (
                        <span
                          className={`inline-flex px-2.5 py-1 rounded-full text-xs font-medium ${
                            OUTCOME_STYLES[call.outcome] || 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                          }`}
                        >
                          {call.outcome}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {expandedId === call.id ? (
                        <ChevronUp className="w-4 h-4 text-gray-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      )}
                    </td>
                  </tr>
                  {/* Expanded transcript */}
                  {expandedId === call.id && expandedCall && (
                    <tr>
                      <td colSpan={5} className="px-6 py-4 bg-gray-50 dark:bg-gray-900">
                        <div className="max-w-3xl">
                          {call.summary && (
                            <div className="mb-4 p-3 bg-primary-50 dark:bg-primary-900/30 rounded-lg">
                              <p className="text-sm font-medium text-primary-700 dark:text-primary-300">Summary</p>
                              <p className="text-sm text-primary-600 dark:text-primary-400 mt-1">{call.summary}</p>
                            </div>
                          )}
                          <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Transcript</p>
                          <div className="space-y-3">
                            {(expandedCall.transcript || []).map((msg, i) => (
                              <div
                                key={i}
                                className={`flex gap-3 ${
                                  msg.role === 'assistant' ? '' : 'justify-end'
                                }`}
                              >
                                <div
                                  className={`max-w-md p-3 rounded-lg text-sm ${
                                    msg.role === 'assistant'
                                      ? 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300'
                                      : 'bg-primary-500 text-white'
                                  }`}
                                >
                                  <p className="text-xs font-medium mb-1 opacity-70">
                                    {msg.role === 'assistant' ? 'Sarah (AI)' : 'Caller'}
                                  </p>
                                  {msg.content}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        {pages > 1 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Page {page} of {pages}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-700 rounded-md disabled:opacity-40 hover:bg-white dark:hover:bg-gray-700 dark:text-gray-300 transition-colors"
              >
                Previous
              </button>
              <button
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page >= pages}
                className="px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-700 rounded-md disabled:opacity-40 hover:bg-white dark:hover:bg-gray-700 dark:text-gray-300 transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
