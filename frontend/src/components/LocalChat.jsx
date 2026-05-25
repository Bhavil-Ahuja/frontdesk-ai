/**
 * LocalChat — chat UI replacement for Vapi when LOCAL_CHAT_MODE is on.
 *
 * Talks to POST /api/chat/stream which returns OpenAI chat.completion.chunk SSE
 * events (the IDENTICAL wire format Vapi consumes). We parse each `data: {...}`
 * frame and append `delta.content` tokens to the in-flight assistant bubble as
 * they stream in — so the UX matches Vapi's transcript stream.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Send, RotateCcw, Bot, User as UserIcon, MessageSquare, Phone, Plus, Trash2, ChevronDown, Download } from 'lucide-react';
import { getToken } from '../lib/api';

// Stable per-tab conversation id so multi-turn chat keeps history server-side.
const CONV_KEY = 'scheduler_ai_chat_conv';
const MSGS_KEY = 'scheduler_ai_chat_msgs';
const STREAM_KEY = 'scheduler_ai_chat_stream'; // tracks in-flight stream

function ensureConversationId() {
  let id = sessionStorage.getItem(CONV_KEY);
  if (!id) {
    id = (crypto?.randomUUID?.() || `conv-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    sessionStorage.setItem(CONV_KEY, id);
  }
  return id;
}

// ── Background stream manager ─────────────────────────────────────────────
// Keeps the stream alive even when the component unmounts (user navigates away).
// Tokens are saved to sessionStorage so the response persists across route changes.
const backgroundStream = {
  active: false,
  abortController: null,
  onUpdate: null, // callback to notify mounted component of new tokens

  start(fetchPromise, abortController) {
    this.active = true;
    this.abortController = abortController;
    sessionStorage.setItem(STREAM_KEY, 'active');
  },

  appendToken(token) {
    // Update sessionStorage directly (persists even if component unmounted)
    try {
      const msgs = JSON.parse(sessionStorage.getItem(MSGS_KEY) || '[]');
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'assistant') {
        last.content = (last.content || '') + token;
        sessionStorage.setItem(MSGS_KEY, JSON.stringify(msgs));
      }
    } catch (_) { /* ignore */ }
    // Also notify mounted component if listening
    if (this.onUpdate) this.onUpdate(token);
  },

  finish(error = null) {
    this.active = false;
    this.abortController = null;
    sessionStorage.removeItem(STREAM_KEY);
    // Mark message as complete in sessionStorage
    try {
      const msgs = JSON.parse(sessionStorage.getItem(MSGS_KEY) || '[]');
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'assistant') {
        delete last.pending;
        if (error && !last.content) {
          last.content = `_(error: ${error})_`;
        }
        sessionStorage.setItem(MSGS_KEY, JSON.stringify(msgs));
      }
    } catch (_) { /* ignore */ }
    // Notify mounted component
    if (this.onUpdate) this.onUpdate(null, true, error);
  },

  abort() {
    if (this.abortController) {
      this.abortController.abort();
    }
    this.active = false;
    sessionStorage.removeItem(STREAM_KEY);
  },

  isActive() {
    return this.active || sessionStorage.getItem(STREAM_KEY) === 'active';
  },
};

const DEFAULT_WELCOME = {
  role: 'assistant',
  content:
    "Hi! I'm your AI agent — same brain that powers the voice call, just over chat. Ask me to book an appointment, look up open slots, or anything you'd say on a real call.",
};

function loadMessages() {
  try {
    const raw = sessionStorage.getItem(MSGS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch (_) { /* corrupted — ignore */ }
  return [DEFAULT_WELCOME];
}

function saveMessages(msgs) {
  try {
    // Strip pending flags before persisting
    const clean = msgs.map(({ pending, ...rest }) => rest);
    sessionStorage.setItem(MSGS_KEY, JSON.stringify(clean));
  } catch (_) { /* storage full — ignore */ }
}

export default function LocalChat() {
  const [messages, setMessages] = useState(loadMessages);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(null);
  // Unified test callers: [{phone, name}, ...]
  const [testCallers, setTestCallers] = useState([]);
  const [selectedCaller, setSelectedCaller] = useState(null); // {phone, name}
  const [callerDropdownOpen, setCallerDropdownOpen] = useState(false);
  const [addingCaller, setAddingCaller] = useState(false);
  const [newCallerName, setNewCallerName] = useState('');
  const [deletingCaller, setDeletingCaller] = useState(null);
  const conversationId = useRef(ensureConversationId());
  const callerDropdownRef = useRef(null);

  // Fetch test callers from config
  const fetchConfig = useCallback(() => {
    const token = getToken();
    fetch('/api/config', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.json() : {}))
      .then((cfg) => {
        const callers = cfg?.test_callers || [];
        setTestCallers(callers);
        // Set selected caller (prefer current selection if still exists)
        setSelectedCaller((prev) => {
          if (prev && callers.some((c) => c.phone === prev.phone)) {
            return callers.find((c) => c.phone === prev.phone);
          }
          return callers[0] || null;
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (callerDropdownRef.current && !callerDropdownRef.current.contains(e.target)) {
        setCallerDropdownOpen(false);
        setAddingCaller(false);
        setNewCallerName('');
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Add a new test caller (generates phone, user provides name)
  async function handleAddCaller() {
    const name = newCallerName.trim();
    if (!name || name.length < 2) {
      setError('Name must be at least 2 characters.');
      return;
    }
    setAddingCaller(true);
    try {
      const token = getToken();
      const resp = await fetch('/api/config/test-callers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ name }),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j.detail || `Failed (${resp.status})`);
      }
      const data = await resp.json();
      setTestCallers(data.test_callers || []);
      // Auto-select the newly created caller
      if (data.caller) setSelectedCaller(data.caller);
      setNewCallerName('');
      setCallerDropdownOpen(false);
    } catch (err) {
      setError(err.message || 'Failed to add test caller.');
    } finally {
      setAddingCaller(false);
    }
  }

  // Delete a test caller
  async function handleDeleteCaller(phone) {
    setDeletingCaller(phone);
    try {
      const token = getToken();
      const resp = await fetch(`/api/config/test-callers/${encodeURIComponent(phone)}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j.detail || `Failed (${resp.status})`);
      }
      const data = await resp.json();
      const remaining = data.test_callers || [];
      setTestCallers(remaining);
      // If we deleted the selected caller, switch to first remaining
      if (selectedCaller?.phone === phone) {
        setSelectedCaller(remaining[0] || null);
      }
    } catch (err) {
      setError(err.message || 'Failed to delete test caller.');
    } finally {
      setDeletingCaller(null);
    }
  }

  // Persist messages to sessionStorage whenever they change
  useEffect(() => {
    saveMessages(messages);
  }, [messages]);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);

  // Subscribe to background stream updates (for when component remounts mid-stream)
  useEffect(() => {
    // Check if there's an active background stream we need to listen to
    if (backgroundStream.isActive()) {
      setStreaming(true);
    }

    // Register callback to receive token updates from background stream
    backgroundStream.onUpdate = (token, done, error) => {
      if (done) {
        // Stream finished while we were mounted or just remounted
        setStreaming(false);
        if (error) {
          setError(error);
        }
        // Reload messages from sessionStorage to get final state
        setMessages(loadMessages());
      } else if (token) {
        // New token arrived — update the last message
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'assistant') {
            next[next.length - 1] = {
              ...last,
              content: (last.content || '') + token,
            };
          }
          return next;
        });
      }
    };

    // On mount, sync with sessionStorage (in case stream completed while away)
    if (!backgroundStream.active && sessionStorage.getItem(STREAM_KEY) !== 'active') {
      setMessages(loadMessages());
      setStreaming(false);
    }

    return () => {
      // Don't abort on unmount — let background stream continue
      backgroundStream.onUpdate = null;
    };
  }, []);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streaming]);

  async function sendMessage(e) {
    e?.preventDefault?.();
    const text = input.trim();
    if (!text || streaming) return;

    setError(null);
    setInput('');

    // Add user message and pending assistant bubble
    const newMessages = [
      ...messages,
      { role: 'user', content: text },
      { role: 'assistant', content: '', pending: true },
    ];
    setMessages(newMessages);
    saveMessages(newMessages); // persist immediately for background stream
    setStreaming(true);

    const token = getToken();
    const controller = new AbortController();
    abortRef.current = controller;
    backgroundStream.start(null, controller);

    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId.current,
          test_phone: selectedCaller?.phone || undefined,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try {
          const j = await res.json();
          detail = j.detail || detail;
        } catch (_) {
          /* not JSON */
        }
        throw new Error(detail);
      }
      if (!res.body) throw new Error('No response body for streaming.');

      // ── Parse SSE: each event is `data: <payload>\n\n` ────────────────
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split on the SSE event terminator
        let sepIdx;
        while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
          const rawEvent = buffer.slice(0, sepIdx);
          buffer = buffer.slice(sepIdx + 2);

          // An event may contain multiple lines; we only care about `data:` lines
          const dataLines = rawEvent
            .split('\n')
            .filter((l) => l.startsWith('data:'))
            .map((l) => l.slice(5).trimStart());
          if (dataLines.length === 0) continue;

          const payload = dataLines.join('\n');
          if (payload === '[DONE]') {
            // Terminator — finalize the stream
            backgroundStream.finish();
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === 'assistant') {
                next[next.length - 1] = { ...last, pending: false };
              }
              return next;
            });
            continue;
          }

          let chunk;
          try {
            chunk = JSON.parse(payload);
          } catch (err) {
            console.warn('[LocalChat] bad SSE payload', payload);
            continue;
          }

          // OpenAI chat.completion.chunk shape — same as Vapi consumes
          const delta = chunk?.choices?.[0]?.delta || {};
          if (typeof delta.content === 'string' && delta.content.length > 0) {
            // Update both sessionStorage (for background persistence) and React state
            backgroundStream.appendToken(delta.content);
            // React state update happens via backgroundStream.onUpdate callback
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // Manual abort (e.g., reset button) — not navigation
        backgroundStream.finish('cancelled');
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'assistant') {
            const content = last.content || '';
            next[next.length - 1] = {
              ...last,
              content: content ? `${content}\n\n_(cancelled)_` : '_(cancelled)_',
              pending: false,
            };
          }
          return next;
        });
      } else {
        console.error('[LocalChat] stream error:', err);
        backgroundStream.finish(err.message);
        setError(err.message || 'Failed to reach the agent.');
        // Drop the empty pending bubble
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'assistant' && last.pending && !last.content) {
            next.pop();
          }
          return next;
        });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  async function resetConversation() {
    // Abort any background stream
    backgroundStream.abort();
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const oldId = conversationId.current;
    // Tell the backend to drop the session
    const token = getToken();
    try {
      await fetch('/api/chat/reset', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: 'reset',
          conversation_id: oldId,
          test_phone: selectedCaller?.phone || undefined,
        }),
      });
    } catch (err) {
      console.warn('[LocalChat] reset request failed:', err);
    }

    // Generate a fresh conversation id and clear UI history
    const fresh =
      crypto?.randomUUID?.() || `conv-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(CONV_KEY, fresh);
    sessionStorage.removeItem(MSGS_KEY);
    conversationId.current = fresh;
    setMessages([
      {
        role: 'assistant',
        content: "Fresh conversation started. How can I help?",
      },
    ]);
    setError(null);
  }

  function exportChat() {
    const exportData = {
      exported_at: new Date().toISOString(),
      conversation_id: conversationId.current,
      test_caller: selectedCaller || null,
      messages: messages.map(({ pending, ...rest }) => rest), // strip pending flags
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-export-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-8 py-6 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-primary-100 dark:bg-primary-900/50 rounded-xl flex items-center justify-center">
            <MessageSquare className="w-5 h-5 text-primary-600" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">Test Agent Responses</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Same LLM + tools as the voice agent — chat to test before going live.
            </p>
          </div>
          {/* ── Unified Test Caller selector dropdown (phone + name) ─────────── */}
          {testCallers.length > 0 && (
            <div className="relative ml-2" ref={callerDropdownRef}>
              <button
                type="button"
                onClick={() => setCallerDropdownOpen((v) => !v)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-50 dark:bg-teal-900/30 border border-teal-200 dark:border-teal-800 rounded-lg hover:bg-teal-100 dark:hover:bg-teal-900/50 transition-colors"
              >
                <Phone className="w-3.5 h-3.5 text-teal-600" />
                <span className="text-xs font-medium text-teal-700 dark:text-teal-400">
                  {selectedCaller ? `${selectedCaller.phone}` : 'Select caller'}
                </span>
                {selectedCaller?.name && (
                  <span className="text-xs text-teal-600 dark:text-teal-400 bg-teal-100 dark:bg-teal-900/50 px-1.5 py-0.5 rounded-full font-medium">
                    {selectedCaller.name}
                  </span>
                )}
                <ChevronDown className={`w-3 h-3 text-teal-500 transition-transform ${callerDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              {callerDropdownOpen && (
                <div className="absolute top-full left-0 mt-1 w-72 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg z-50 py-1">
                  <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-700">
                    <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Test Callers</p>
                    <p className="text-[10px] text-gray-400 mt-0.5">Each phone maps to a unique patient</p>
                  </div>
                  <div className="max-h-48 overflow-y-auto">
                    {testCallers.map((caller) => (
                      <div
                        key={caller.phone}
                        className={`flex items-center justify-between px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer ${
                          caller.phone === selectedCaller?.phone ? 'bg-teal-50 dark:bg-teal-900/30' : ''
                        }`}
                      >
                        <button
                          type="button"
                          className="flex items-center gap-2 flex-1 text-left"
                          onClick={async () => {
                            if (caller.phone !== selectedCaller?.phone) {
                              // Switching callers — reset old session first, then switch
                              await resetConversation();
                              setSelectedCaller(caller);
                            }
                            setCallerDropdownOpen(false);
                          }}
                        >
                          <div className="flex flex-col">
                            <span className={`text-sm ${caller.phone === selectedCaller?.phone ? 'font-semibold text-teal-700 dark:text-teal-400' : 'text-gray-700 dark:text-gray-300'}`}>
                              {caller.name}
                            </span>
                            <span className={`text-xs ${caller.phone === selectedCaller?.phone ? 'text-teal-600 dark:text-teal-400' : 'text-gray-400'}`}>
                              {caller.phone}
                            </span>
                          </div>
                          {caller.phone === selectedCaller?.phone && (
                            <span className="text-[10px] bg-teal-100 dark:bg-teal-900/50 text-teal-600 dark:text-teal-400 px-1.5 py-0.5 rounded-full font-medium ml-2">active</span>
                          )}
                        </button>
                        {testCallers.length > 1 && (
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleDeleteCaller(caller.phone); }}
                            disabled={deletingCaller === caller.phone}
                            className="p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded transition-colors disabled:opacity-50"
                            title="Delete this test caller"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="border-t border-gray-100 dark:border-gray-700 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={newCallerName}
                        onChange={(e) => setNewCallerName(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddCaller(); } }}
                        placeholder="New patient name..."
                        className="flex-1 px-2 py-1.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-1 focus:ring-teal-500 focus:border-teal-500 dark:bg-gray-700 dark:text-white"
                        maxLength={50}
                      />
                      <button
                        type="button"
                        onClick={handleAddCaller}
                        disabled={addingCaller || !newCallerName.trim() || testCallers.length >= 10}
                        className="flex items-center gap-1 px-2 py-1.5 text-sm text-white bg-teal-500 hover:bg-teal-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Add new test caller (phone auto-generated)"
                      >
                        <Plus className="w-3.5 h-3.5" />
                        {addingCaller ? '...' : 'Add'}
                      </button>
                    </div>
                    <p className="text-[10px] text-gray-400 mt-1">Phone number auto-generated • {testCallers.length}/10</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={exportChat}
            className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 transition-colors"
            title="Export conversation as JSON for debugging"
          >
            <Download className="w-4 h-4" />
            Export
          </button>
          <button
            onClick={resetConversation}
            className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 transition-colors"
            title="Start a new conversation (clears server-side session)"
          >
            <RotateCcw className="w-4 h-4" />
            New chat
          </button>
        </div>
      </div>

      {/* Message list */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-8 py-6 space-y-4">
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {error && (
          <div className="max-w-3xl mx-auto px-4 py-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-400 text-sm rounded-lg">
            {error}
          </div>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={sendMessage}
        className="px-8 py-4 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
      >
        <div className="flex items-end gap-3 max-w-3xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder="Type a message — e.g. 'book a cleaning next Tuesday'"
            rows={1}
            className="flex-1 resize-none px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent text-sm dark:bg-gray-700 dark:text-white"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="px-5 py-3 bg-primary-500 text-white rounded-xl font-medium text-sm hover:bg-primary-600 disabled:bg-gray-300 dark:disabled:bg-gray-600 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
            {streaming ? 'Streaming…' : 'Send'}
          </button>
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-2 text-center">
          Press Enter to send · Shift+Enter for newline
        </p>
      </form>
    </div>
  );
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user';
  return (
    <div className={`flex gap-3 max-w-3xl mx-auto ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
          isUser ? 'bg-gray-200 text-gray-700 dark:bg-gray-600 dark:text-gray-300' : 'bg-primary-100 text-primary-700 dark:bg-primary-900/50 dark:text-primary-400'
        }`}
      >
        {isUser ? <UserIcon className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>
      <div
        className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-primary-500 text-white rounded-tr-sm'
            : 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100 rounded-tl-sm'
        }`}
      >
        {message.content || (message.pending ? <TypingDots /> : '')}
        {message.pending && message.content ? <span className="ml-1 animate-pulse">▍</span> : null}
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1 items-center">
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '120ms' }} />
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '240ms' }} />
    </span>
  );
}
