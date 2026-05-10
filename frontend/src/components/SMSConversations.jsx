import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  MessageSquare,
  ArrowLeft,
  RefreshCw,
  AlertCircle,
  Phone,
  Send,
  ArrowDown,
  ArrowUp,
  Clock,
  Inbox,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatDateTime, formatRelativeTime as fmtRelative } from '../lib/timezone';

export default function SMSConversations() {
  const { user } = useAuth();
  const tz = user?.timezone || 'America/Chicago';
  const [conversations, setConversations] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const messagesEndRef = useRef(null);

  const fetchConversations = useCallback(async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    try {
      const data = await apiFetch('/api/sms/conversations');
      setConversations(data || []);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load conversations');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const fetchMessages = useCallback(async (phone) => {
    setLoadingMessages(true);
    try {
      const data = await apiFetch(`/api/sms/messages?patient_phone=${encodeURIComponent(phone)}`);
      setMessages(data || []);
      setError(null);
      // Scroll to bottom after render
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    } catch (err) {
      setError(err.message || 'Failed to load messages');
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  function selectConversation(phone) {
    setSelectedPhone(phone);
    fetchMessages(phone);
  }

  function goBack() {
    setSelectedPhone(null);
    setMessages([]);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          {selectedPhone && (
            <button
              onClick={goBack}
              className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
          )}
          <div>
            <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <MessageSquare className="w-7 h-7 text-primary-500" />
              {selectedPhone ? (
                <>
                  <Phone className="w-5 h-5 text-gray-400" />
                  {selectedPhone}
                </>
              ) : (
                'SMS Conversations'
              )}
            </h2>
            {!selectedPhone && (
              <p className="text-gray-500 mt-1">
                Two-way SMS message history between patients and the AI agent.
              </p>
            )}
          </div>
        </div>
        <button
          onClick={() =>
            selectedPhone ? fetchMessages(selectedPhone) : fetchConversations(true)
          }
          disabled={refreshing || loadingMessages}
          className="flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <RefreshCw
            className={`w-4 h-4 ${refreshing || loadingMessages ? 'animate-spin' : ''}`}
          />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3 mb-6">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Conversation list or message thread */}
      {!selectedPhone ? (
        /* Conversation list */
        conversations.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
            <Inbox className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-gray-900 mb-1">No conversations yet</h3>
            <p className="text-sm text-gray-500">
              SMS conversations will appear here when patients text your Twilio number or receive
              reminders and reply back.
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {conversations.map((conv, idx) => (
              <button
                key={conv.patient_phone}
                onClick={() => selectConversation(conv.patient_phone)}
                className={`w-full flex items-center gap-4 p-4 text-left hover:bg-gray-50 transition-colors ${
                  idx > 0 ? 'border-t border-gray-100' : ''
                }`}
              >
                {/* Avatar */}
                <div className="w-10 h-10 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-sm font-semibold shrink-0">
                  <Phone className="w-4 h-4" />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-gray-900 text-sm">
                      {conv.patient_phone}
                    </span>
                    <span className="text-xs text-gray-400 shrink-0">
                      {conv.last_message_at
                        ? fmtRelative(conv.last_message_at, tz)
                        : ''}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {conv.last_direction === 'INBOUND' ? (
                      <ArrowDown className="w-3 h-3 text-blue-400 shrink-0" />
                    ) : (
                      <ArrowUp className="w-3 h-3 text-green-400 shrink-0" />
                    )}
                    <p className="text-sm text-gray-500 truncate">
                      {conv.last_message_body || 'No messages'}
                    </p>
                  </div>
                </div>

                {/* Message count badge */}
                <span className="px-2.5 py-1 bg-gray-100 text-gray-600 rounded-full text-xs font-medium shrink-0">
                  {conv.message_count}
                </span>
              </button>
            ))}
          </div>
        )
      ) : (
        /* Message thread */
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {loadingMessages ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
          ) : messages.length === 0 ? (
            <div className="p-12 text-center">
              <MessageSquare className="w-12 h-12 text-gray-300 mx-auto mb-3" />
              <p className="text-sm text-gray-500">No messages found for this number.</p>
            </div>
          ) : (
            <div className="max-h-[600px] overflow-y-auto p-4 space-y-3 bg-gray-50">
              {messages.map((msg) => {
                const isOutbound = msg.direction === 'OUTBOUND';
                return (
                  <div
                    key={msg.id}
                    className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[70%] rounded-2xl px-4 py-2.5 ${
                        isOutbound
                          ? 'bg-primary-500 text-white rounded-br-md'
                          : 'bg-white border border-gray-200 text-gray-900 rounded-bl-md'
                      }`}
                    >
                      {/* Direction label */}
                      <div
                        className={`flex items-center gap-1 mb-1 text-xs ${
                          isOutbound ? 'text-primary-100' : 'text-gray-400'
                        }`}
                      >
                        {isOutbound ? (
                          <>
                            <ArrowUp className="w-3 h-3" />
                            AI Agent
                          </>
                        ) : (
                          <>
                            <ArrowDown className="w-3 h-3" />
                            Patient
                          </>
                        )}
                      </div>

                      {/* Message body */}
                      <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>

                      {/* Timestamp */}
                      <div
                        className={`flex items-center gap-1 mt-1 text-xs ${
                          isOutbound ? 'text-primary-200' : 'text-gray-400'
                        }`}
                      >
                        <Clock className="w-3 h-3" />
                        {msg.created_at
                          ? formatDateTime(msg.created_at, tz)
                          : ''}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────
// formatRelativeTime is now imported from lib/timezone.js as fmtRelative
