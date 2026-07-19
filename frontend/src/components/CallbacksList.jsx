import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  Phone,
  PhoneCall,
  CheckCircle,
  Circle,
  Clock,
  User,
  AlertCircle,
  Loader2,
  CalendarDays,
  X,
  PhoneOff,
  UserCircle,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

export default function CallbacksList() {
  const { user } = useAuth();
  const tz = user?.timezone || 'Asia/Kolkata';

  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('PENDING'); // 'PENDING' or 'ATTENDED'
  const [staffPhone, setStaffPhone] = useState(user?.business_phone || user?.owner_phone || '');
  
  // Call dialing states
  const [dialingPhone, setDialingPhone] = useState(null);
  const [dialingCallId, setDialingCallId] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const fetchCallbacks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch(`/api/calls?page_size=100&outcome=ESCALATED`);
      setCalls(data.items || []);
    } catch (err) {
      console.error('Failed to fetch callbacks:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCallbacks();
  }, [fetchCallbacks]);

  const handleToggleAttended = async (callId, currentStatus) => {
    try {
      const nextStatus = !currentStatus;
      await apiFetch(`/api/calls/${callId}/attended?attended=${nextStatus}`, {
        method: 'PUT',
      });
      setCalls((prev) =>
        prev.map((c) => (c.id === callId ? { ...c, attended: nextStatus } : c))
      );
    } catch (err) {
      console.error('Failed to toggle attended status:', err);
    }
  };

  const handleInitiateCallback = async (e) => {
    e.preventDefault();
    if (!staffPhone.trim() || !dialingPhone) return;
    setConnecting(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      await apiFetch(`/api/calls/connect-bridged`, {
        method: 'POST',
        body: {
          staff_phone: staffPhone.trim(),
          customer_phone: dialingPhone,
        },
      });
      setSuccessMessage('Exotel is now calling your phone. Please pick up to connect to the customer.');
      
      // Auto-mark the callback log as attended if we have a call ID associated with this dial
      if (dialingCallId) {
        try {
          await apiFetch(`/api/calls/${dialingCallId}/attended?attended=true`, {
            method: 'PUT',
          });
        } catch (mErr) {
          console.error('Failed to auto-mark call as attended:', mErr);
        }
      }

      // Refresh list to pull updated state after a short delay
      setTimeout(() => {
        fetchCallbacks();
        setDialingPhone(null);
        setDialingCallId(null);
      }, 4000);
    } catch (err) {
      console.error('Failed to initiate bridged callback:', err);
      setErrorMessage(err.message || 'Failed to initiate bridged call. Please check your credentials or phone format.');
    } finally {
      setConnecting(false);
    }
  };

  const filteredCalls = calls.filter((c) => {
    if (activeTab === 'PENDING') return !c.attended;
    return c.attended;
  });

  const formatCallDate = (isoStr) => {
    if (!isoStr) return '';
    try {
      return new Date(isoStr).toLocaleString('en-US', {
        timeZone: tz,
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
      });
    } catch {
      return new Date(isoStr).toLocaleDateString();
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-indigo-50 dark:bg-indigo-900/30 rounded-xl flex items-center justify-center border border-indigo-100/50 dark:border-indigo-500/10">
            <PhoneCall className="w-6 h-6 text-indigo-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              Callbacks Dashboard
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Manage escalated calls and trigger bridged callback dials via Exotel
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 max-w-sm">
        <button
          onClick={() => setActiveTab('PENDING')}
          className={`flex-1 px-4 py-2 rounded-lg text-xs font-semibold transition-all whitespace-nowrap ${
            activeTab === 'PENDING'
              ? 'bg-white dark:bg-gray-700 text-gray-950 dark:text-white shadow-sm'
              : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
          }`}
        >
          Pending Callbacks ({calls.filter((c) => !c.attended).length})
        </button>
        <button
          onClick={() => setActiveTab('ATTENDED')}
          className={`flex-1 px-4 py-2 rounded-lg text-xs font-semibold transition-all whitespace-nowrap ${
            activeTab === 'ATTENDED'
              ? 'bg-white dark:bg-gray-700 text-gray-950 dark:text-white shadow-sm'
              : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
          }`}
        >
          Attended ({calls.filter((c) => c.attended).length})
        </button>
      </div>

      {/* Callback list container */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
        </div>
      ) : filteredCalls.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900/40 rounded-2xl border border-gray-200/80 dark:border-white/5 p-8">
          <PhoneOff className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-gray-900 dark:text-white">No callbacks in this section</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-xs mx-auto">
            {activeTab === 'PENDING'
              ? 'All escalated calls have been marked as attended. Nice job!'
              : 'No calls have been marked as attended yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredCalls.map((call) => (
            <div
              key={call.id}
              className="bg-white dark:bg-gray-900/60 rounded-2xl border border-gray-200/80 dark:border-white/5 p-5 md:p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 transition-all hover:border-gray-350 dark:hover:border-white/10"
            >
              <div className="space-y-2 flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="flex items-center gap-1.5 text-sm font-semibold text-gray-900 dark:text-white">
                    <UserCircle className="w-4 h-4 text-indigo-400" />
                    <span>{call.caller_number}</span>
                  </div>
                  <span className="text-xs text-gray-400 dark:text-white/30">•</span>
                  <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                    <CalendarDays className="w-3.5 h-3.5" />
                    <span>{formatCallDate(call.started_at)}</span>
                  </div>
                  {call.duration_seconds && (
                    <>
                      <span className="text-xs text-gray-400 dark:text-white/30">•</span>
                      <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{Math.round(call.duration_seconds / 60)}m duration</span>
                      </div>
                    </>
                  )}
                </div>

                <div className="bg-gray-50 dark:bg-white/5 rounded-xl p-3 text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap border border-gray-100 dark:border-white/5">
                  <p className="font-semibold text-xs text-indigo-500 dark:text-indigo-400 mb-1 uppercase tracking-wider">Escalation Summary</p>
                  {call.summary || 'Caller requested to speak with a human agent.'}
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3 w-full md:w-auto shrink-0 justify-end">
                {/* Attended Checkbox */}
                <button
                  onClick={() => handleToggleAttended(call.id, call.attended)}
                  className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold border transition-all ${
                    call.attended
                      ? 'bg-green-50 dark:bg-green-500/10 text-green-700 dark:text-green-400 border-green-200 dark:border-green-800'
                      : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700'
                  }`}
                  title={call.attended ? 'Mark as Pending' : 'Mark as Attended'}
                >
                  {call.attended ? <CheckCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>{call.attended ? 'Attended' : 'Mark Attended'}</span>
                </button>

                {/* Dial Trigger */}
                <button
                  onClick={() => {
                    setDialingPhone(call.caller_number);
                    setDialingCallId(call.id);
                    setSuccessMessage('');
                    setErrorMessage('');
                  }}
                  className="inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-500 hover:bg-indigo-600 text-white rounded-xl text-xs font-semibold transition-all shadow-sm hover:shadow-indigo-500/10"
                >
                  <Phone className="w-3.5 h-3.5" />
                  <span>Call Back</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Exotel Click-to-Call modal */}
      {dialingPhone && createPortal(
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          {/* Overlay */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => {
              setDialingPhone(null);
              setDialingCallId(null);
            }}
          />

          {/* Dialog Container */}
          <div className="relative bg-white dark:bg-gray-900 border border-gray-250 dark:border-white/10 w-full max-w-md rounded-2xl p-6 shadow-2xl space-y-4 z-[70] animate-scale-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <PhoneCall className="w-5 h-5 text-indigo-500" />
                Connect Bridged Callback
              </h3>
              <button
                onClick={() => {
                  setDialingPhone(null);
                  setDialingCallId(null);
                }}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-white p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-all"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Exotel will dial your phone number first. Once you answer, Exotel will place a call to the student and bridge you together. The student will only see your official AI number as the Caller ID.
            </p>

            <form onSubmit={handleInitiateCallback} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1.5">
                  Your Phone Number
                </label>
                <input
                  type="text"
                  value={staffPhone}
                  onChange={(e) => setStaffPhone(e.target.value)}
                  placeholder="e.g. +91 98765 43210"
                  className="w-full px-3 py-2.5 border border-gray-250 dark:border-white/10 rounded-xl text-sm bg-gray-50 dark:bg-white/5 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-white/30 focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 outline-none transition-all"
                  required
                />
              </div>

              {errorMessage && (
                <div className="flex items-start gap-2 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/10 rounded-xl p-3 border border-red-200 dark:border-red-800 text-xs">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{errorMessage}</span>
                </div>
              )}

              {successMessage && (
                <div className="flex items-start gap-2 text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-500/10 rounded-xl p-3 border border-green-200 dark:border-green-800 text-xs">
                  <CheckCircle className="w-4 h-4 shrink-0" />
                  <span>{successMessage}</span>
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setDialingPhone(null);
                    setDialingCallId(null);
                  }}
                  className="px-4 py-2 border border-gray-250 dark:border-white/10 text-gray-700 dark:text-gray-300 rounded-xl text-xs font-semibold hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={connecting || !staffPhone.trim()}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-xl text-xs font-semibold transition-colors disabled:opacity-50"
                >
                  {connecting ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Connecting...</span>
                    </>
                  ) : (
                    <>
                      <Phone className="w-3.5 h-3.5" />
                      <span>Connect Call</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
