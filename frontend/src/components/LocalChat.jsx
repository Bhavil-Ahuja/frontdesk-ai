/**
 * LocalChat — chat UI replacement for Vapi when LOCAL_CHAT_MODE is on.
 *
 * Talks to POST /api/chat/stream which returns OpenAI chat.completion.chunk SSE
 * events (the IDENTICAL wire format Vapi consumes). We parse each `data: {...}`
 * frame and append `delta.content` tokens to the in-flight assistant bubble as
 * they stream in — so the UX matches Vapi's transcript stream.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Send, RotateCcw, Bot, User as UserIcon, MessageSquare } from 'lucide-react';
import { getToken } from '../lib/api';

// Stable per-tab conversation id so multi-turn chat keeps history server-side.
const CONV_KEY = 'scheduler_ai_chat_conv';
const MSGS_KEY = 'scheduler_ai_chat_msgs';

function ensureConversationId() {
  let id = sessionStorage.getItem(CONV_KEY);
  if (!id) {
    id = (crypto?.randomUUID?.() || `conv-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    sessionStorage.setItem(CONV_KEY, id);
  }
  return id;
}

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
  const conversationId = useRef(ensureConversationId());

  // Persist messages to sessionStorage whenever they change
  useEffect(() => {
    saveMessages(messages);
  }, [messages]);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);

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
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '', pending: true },
    ]);
    setStreaming(true);

    const token = getToken();
    const controller = new AbortController();
    abortRef.current = controller;

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
            // Terminator — finalize the in-flight bubble
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
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === 'assistant') {
                next[next.length - 1] = {
                  ...last,
                  content: (last.content || '') + delta.content,
                };
              }
              return next;
            });
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // user-initiated cancel — just unmark pending
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'assistant') {
            next[next.length - 1] = {
              ...last,
              content: last.content || '_(cancelled)_',
              pending: false,
            };
          }
          return next;
        });
      } else {
        console.error('[LocalChat] stream error:', err);
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
    if (streaming && abortRef.current) {
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
        body: JSON.stringify({ message: 'reset', conversation_id: oldId }),
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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-8 py-6 border-b border-gray-200 bg-white flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-dental-100 rounded-xl flex items-center justify-center">
            <MessageSquare className="w-5 h-5 text-dental-600" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Test Agent Responses</h1>
            <p className="text-sm text-gray-500">
              Same LLM + tools as the voice agent — chat to test before going live.
            </p>
          </div>
        </div>
        <button
          onClick={resetConversation}
          className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 rounded-lg hover:bg-gray-50 hover:text-gray-900 border border-gray-200 transition-colors"
          title="Start a new conversation (clears server-side session)"
        >
          <RotateCcw className="w-4 h-4" />
          New chat
        </button>
      </div>

      {/* Message list */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-8 py-6 space-y-4">
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {error && (
          <div className="max-w-3xl mx-auto px-4 py-3 bg-red-50 border border-red-200 text-red-800 text-sm rounded-lg">
            {error}
          </div>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={sendMessage}
        className="px-8 py-4 border-t border-gray-200 bg-white"
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
            className="flex-1 resize-none px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-dental-500 focus:border-transparent text-sm"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="px-5 py-3 bg-dental-500 text-white rounded-xl font-medium text-sm hover:bg-dental-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
            {streaming ? 'Streaming…' : 'Send'}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-2 text-center">
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
          isUser ? 'bg-gray-200 text-gray-700' : 'bg-dental-100 text-dental-700'
        }`}
      >
        {isUser ? <UserIcon className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>
      <div
        className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-dental-500 text-white rounded-tr-sm'
            : 'bg-white border border-gray-200 text-gray-900 rounded-tl-sm'
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
