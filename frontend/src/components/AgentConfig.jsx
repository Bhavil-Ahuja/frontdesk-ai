import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Power,
  Phone as PhoneIcon,
  Clock,
  MessageSquare,
  Mic,
  Save,
  CheckCircle,
  AlertCircle,
  Bot,
  CalendarCheck,
  Mail,
  Building2,
  Eye,
  EyeOff,
  Link as LinkIcon,
  Plus,
  Trash2,
  Stethoscope,
  Bell,
  Star,
  ToggleLeft,
  ToggleRight,
  Play,
  Square,
  Volume2,
  Loader2,
  AlertTriangle,
  CalendarX,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getToken } from '../lib/api';
import { useModal } from '../contexts/ModalContext';
import { useAuth } from '../contexts/AuthContext';
import ThemedDatePicker from './ui/ThemedDatePicker';
import PhoneInput, { countryFromTimezone } from './ui/PhoneInput';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

// Convert an appointment-type display name into the lowercase underscored
// "code" the backend stores internally. Strips non-alphanumerics so users
// never have to think about slugs / IDs.
function slugifyTypeName(name) {
  return (name || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}
const VOICE_OPTIONS = [
  { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel', description: 'Young female, warm and professional tone' },
  { id: 'AZnzlk1XvdvUeBnXmlld', name: 'Domi', description: 'Young female, confident and direct delivery' },
  { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella', description: 'Young female, soft and friendly manner' },
  { id: 'MF3mGyEYCl7XYWbV9V6O', name: 'Emily', description: 'Young female, calm and gentle cadence' },
  { id: 'TxGEqnHWrfWFTfGW9XjX', name: 'Josh', description: 'Young male, deep and reassuring voice' },
];

export default function AgentConfig() {
  const { isAdmin } = useAuth();
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const [showSecrets, setShowSecrets] = useState({});

  // Voice preview state
  const [playingVoiceId, setPlayingVoiceId] = useState(null);
  const [loadingVoiceId, setLoadingVoiceId] = useState(null);
  const audioRef = useRef(null);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      window.speechSynthesis?.cancel();
    };
  }, []);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    window.speechSynthesis?.cancel();
    setPlayingVoiceId(null);
    setLoadingVoiceId(null);
  }, []);

  const playVoicePreview = useCallback(async (voiceId) => {
    // If already playing this voice, stop it
    if (playingVoiceId === voiceId) {
      stopAudio();
      return;
    }

    // Stop any currently playing audio
    stopAudio();
    setLoadingVoiceId(voiceId);

    try {
      // Try the backend ElevenLabs endpoint first
      const token = getToken();
      const resp = await fetch(`/api/voice-preview/${voiceId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;

        audio.onplay = () => {
          setLoadingVoiceId(null);
          setPlayingVoiceId(voiceId);
        };
        audio.onended = () => {
          setPlayingVoiceId(null);
          URL.revokeObjectURL(url);
          audioRef.current = null;
        };
        audio.onerror = () => {
          setPlayingVoiceId(null);
          setLoadingVoiceId(null);
          URL.revokeObjectURL(url);
          audioRef.current = null;
        };

        await audio.play();
        return;
      }

      // Fallback: use browser SpeechSynthesis. We make each VOICE_OPTION sound
      // distinct by (a) deterministically picking a different OS voice from
      // the matching gender pool based on the voice index, and (b) varying
      // rate/pitch slightly per voice.
      if ('speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance(
          'Hi there! Thank you for calling. How can I help you today?'
        );

        const voices = window.speechSynthesis.getVoices();
        const voiceMeta = VOICE_OPTIONS.find((v) => v.id === voiceId);
        const voiceIdx = VOICE_OPTIONS.findIndex((v) => v.id === voiceId);

        // Vary pitch/rate so even when all OS voices are identical, the user
        // can still tell the previews apart. Range stays in a natural band.
        utterance.rate = 0.9 + (voiceIdx % 5) * 0.04;   // 0.90, 0.94, 0.98, 1.02, 1.06
        utterance.pitch = 0.85 + (voiceIdx % 5) * 0.10; // 0.85, 0.95, 1.05, 1.15, 1.25

        if (voiceMeta && voices.length > 0) {
          const desc = (voiceMeta.description || '').toLowerCase();
          const isMale = desc.includes('male') && !desc.includes('female');
          // Pool of en-* voices matching the expected gender (best effort —
          // browsers don't expose gender directly, so we match on name).
          const enVoices = voices.filter((v) => v.lang.startsWith('en'));
          const genderPool = enVoices.filter((v) => {
            const n = v.name.toLowerCase();
            return isMale
              ? n.includes('male') && !n.includes('female')
              : n.includes('female') || /alex|samantha|victoria|karen|tessa|moira|fiona|kate|allison|ava/.test(n);
          });
          const pool = genderPool.length > 0 ? genderPool : enVoices;
          if (pool.length > 0) {
            utterance.voice = pool[voiceIdx % pool.length];
          }
        }

        utterance.onstart = () => {
          setLoadingVoiceId(null);
          setPlayingVoiceId(voiceId);
        };
        utterance.onend = () => setPlayingVoiceId(null);
        utterance.onerror = () => {
          setPlayingVoiceId(null);
          setLoadingVoiceId(null);
        };

        window.speechSynthesis.speak(utterance);
      } else {
        setLoadingVoiceId(null);
      }
    } catch {
      setLoadingVoiceId(null);
      setPlayingVoiceId(null);
    }
  }, [playingVoiceId, stopAudio]);

  useEffect(() => {
    fetchConfig();
  }, []);

  async function fetchConfig() {
    try {
      const data = await apiFetch('/api/config');
      setConfig(data);
    } catch (err) {
      setError(err.message || 'Failed to load config');
    } finally {
      setLoading(false);
    }
  }

  async function saveConfig() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch('/api/config', {
        method: 'PUT',
        body: config,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      // Refresh from server so masked values come back
      await fetchConfig();
    } catch (err) {
      setError(err.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  function update(key, value) {
    setConfig((c) => ({ ...c, [key]: value }));
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  if (!config) {
    return (
      <div className="p-8 text-center text-gray-500 dark:text-gray-400">
        Unable to load agent configuration.
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sticky top-0 bg-gray-50 dark:bg-gray-900 -mx-4 md:-mx-8 px-4 md:px-8 py-3 md:py-4 border-b border-gray-200 dark:border-gray-700 z-10">
        <div>
          <h2 className="text-xl md:text-2xl font-bold text-gray-900 dark:text-white">Agent Configuration</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Manage your AI receptionist settings</p>
        </div>
        <button
          onClick={saveConfig}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50 transition-colors shadow-sm"
        >
          {saved ? (
            <>
              <CheckCircle className="w-4 h-4" /> Saved!
            </>
          ) : (
            <>
              <Save className="w-4 h-4" /> {saving ? 'Saving...' : 'Save Settings'}
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* Agent status (read-only — derived from tenant.status) */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-center gap-3">
          <div
            className={`p-3 rounded-lg ${config.agent_active ? 'bg-green-50 dark:bg-green-900/30' : 'bg-red-50 dark:bg-red-900/30'}`}
          >
            <Power
              className={`w-6 h-6 ${config.agent_active ? 'text-green-600' : 'text-red-600'}`}
            />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Agent Status</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {config.agent_active
                ? 'Your agent is ACTIVE and answering calls.'
                : 'Your agent is paused (status set by admin).'}
            </p>
          </div>
        </div>
      </div>

      {/* Business info */}
      <Section icon={Building2} title="Business Information">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Business Name">
            <input
              type="text"
              value={config.business_name || ''}
              onChange={(e) => update('business_name', e.target.value)}
              className="input"
            />
          </Field>
          <Field label="Business Phone">
            <PhoneInput
              value={config.business_phone || ''}
              onChange={(v) => update('business_phone', v)}
              defaultCountry={countryFromTimezone(config.timezone)}
              placeholder="(512) 555-0100"
            />
          </Field>
          <Field label="Business Address" className="md:col-span-2">
            <input
              type="text"
              value={config.business_address || ''}
              onChange={(e) => update('business_address', e.target.value)}
              placeholder="123 Main St, Austin, TX"
              className="input"
            />
          </Field>
          <Field
            label="Timezone"
            help="Timezone is set at registration and cannot be changed here. Contact support if you need to relocate."
          >
            <input
              type="text"
              value={config.timezone || ''}
              readOnly
              disabled
              tabIndex={-1}
              aria-readonly="true"
              className="input cursor-not-allowed bg-gray-100 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400"
            />
          </Field>
        </div>
      </Section>

      {/* Agent persona */}
      <Section icon={Bot} title="Agent Persona">
        <div className="grid grid-cols-1 gap-4">
          <Field label="Agent Name">
            <input
              type="text"
              value={config.agent_name || ''}
              onChange={(e) => update('agent_name', e.target.value)}
              placeholder="Sarah"
              className="input"
            />
          </Field>
          <Field
            label="Greeting Message"
            help="The first thing the AI agent says when answering a call."
          >
            <textarea
              value={config.greeting_message || ''}
              onChange={(e) => update('greeting_message', e.target.value)}
              rows={3}
              placeholder="Thank you for calling. How can I help you today?"
              className="input resize-none"
            />
          </Field>
          {/* Voice is managed by the platform — show help card instead */}
          <div className="bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-xl p-4">
            <div className="flex items-start gap-3">
              <Mic className="w-5 h-5 text-violet-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-violet-900 dark:text-violet-300">Voice Configuration</p>
                <p className="text-xs text-violet-700 dark:text-violet-400 mt-1">
                  Voice settings are managed by the FrontDesk AI platform. Your agent's voice is automatically configured when your account is provisioned.
                  Need help or want to change your voice? Submit a support ticket.
                </p>
                <a
                  href="/support"
                  className="inline-flex items-center gap-1.5 mt-2 text-xs font-medium text-violet-600 dark:text-violet-400 hover:text-violet-800 dark:hover:text-violet-300 transition-colors"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Go to Support
                </a>
              </div>
            </div>
          </div>
        </div>
      </Section>

      {/* Escalation */}
      <Section icon={PhoneIcon} title="Escalation & Emergencies">
        <div className="space-y-4">
          {/* Prompt the owner to fill in emergency guidance when it's still blank.
              Escalation phone is now collected at signup, so it should already
              be populated — but emergency guidance is optional at signup and
              should be filled in here. */}
          {!config.emergency_guidance?.trim() && (
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4 flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-500 dark:text-amber-400 mt-0.5 shrink-0" />
              <div className="text-sm">
                <p className="font-medium text-amber-900 dark:text-amber-300">
                  Add emergency guidance below
                </p>
                <p className="text-amber-700 dark:text-amber-400 mt-1">
                  Your agent doesn't have any emergency instructions yet. Without
                  this, callers describing a medical emergency may not get
                  appropriate first-aid steps. Add a short list of common
                  scenarios and what the agent should say or do — for example,
                  knocked-out tooth, severe bleeding, chest pain, or trouble
                  breathing.
                </p>
              </div>
            </div>
          )}

          <Field
            label={
              <>
                Escalation Phone Number <span className="text-red-400">*</span>
              </>
            }
            help="When the AI escalates a call, it transfers to this number. Set during signup; update here if it changes."
          >
            <PhoneInput
              value={config.escalation_phone || ''}
              onChange={(v) => update('escalation_phone', v)}
              defaultCountry={countryFromTimezone(config.timezone)}
              placeholder="(512) 555-0100"
            />
          </Field>
          <Field
            label="Emergency Guidance"
            help="First-aid instructions the agent gives callers in emergencies, before transferring. Recommended."
          >
            <textarea
              value={config.emergency_guidance || ''}
              onChange={(e) => update('emergency_guidance', e.target.value)}
              rows={5}
              placeholder={
                '- Knocked-out tooth: keep moist in milk or saliva, come in within 30 minutes, do not touch the root\n' +
                '- Severe bleeding: apply firm pressure with clean gauze, ER if it does not stop\n' +
                '- Chest pain or trouble breathing: call 911 immediately\n' +
                '- Severe swelling or abscess: same-day visit, advise ER if breathing affected'
              }
              className="input resize-none font-mono text-xs"
            />
          </Field>
        </div>
      </Section>

      {/* Business hours */}
      <Section icon={Clock} title="Business Hours">
        <div className="space-y-3">
          {DAYS.map((day) => {
            const hours = config.business_hours?.[day];
            const isOpen = hours !== null && hours !== undefined;
            return (
              <div key={day} className="flex flex-wrap items-center gap-2 md:gap-4">
                <div className="w-20 md:w-24">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300 capitalize">{day}</span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    const bh = { ...(config.business_hours || {}) };
                    bh[day] = isOpen ? null : { open: '08:00', close: '18:00' };
                    update('business_hours', bh);
                  }}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                    isOpen
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                >
                  {isOpen ? 'Open' : 'Closed'}
                </button>
                {isOpen && (
                  <>
                    <input
                      type="time"
                      value={hours.open}
                      onChange={(e) => {
                        const bh = { ...config.business_hours };
                        bh[day] = { ...bh[day], open: e.target.value };
                        update('business_hours', bh);
                      }}
                      className="px-3 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                    />
                    <span className="text-gray-400">to</span>
                    <input
                      type="time"
                      value={hours.close}
                      onChange={(e) => {
                        const bh = { ...config.business_hours };
                        bh[day] = { ...bh[day], close: e.target.value };
                        update('business_hours', bh);
                      }}
                      className="px-3 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                    />
                  </>
                )}
              </div>
            );
          })}
        </div>
      </Section>

      {/* Holidays / Office Closures */}
      <Section icon={CalendarX} title="Holidays & Office Closures">
        <p className="text-sm text-gray-500 dark:text-gray-400 -mt-2 mb-3">
          One-off days the office is closed (in addition to your weekly schedule above).
          The agent will refuse bookings and proactively tell callers we're closed for the named holiday.
          Add as many as you like, edit any time.
        </p>
        <HolidaysEditor
          holidays={config.holidays || []}
          onChange={(list) => update('holidays', list)}
        />
      </Section>

      {/* Appointment Types */}
      <Section icon={Stethoscope} title="Appointment Types">
        <p className="text-sm text-gray-500 dark:text-gray-400 -mt-2 mb-3">
          Define the types of appointments your agent can book. <strong>Max Concurrent</strong> controls
          how many overlapping bookings are allowed per time slot (e.g. 3 means three patients can be
          booked at 10:00 AM simultaneously).
        </p>
        <div className="space-y-3">
          {(config.appointment_types || []).map((at, idx) => (
            <div key={idx} className="flex items-start gap-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3 border border-gray-100 dark:border-gray-700">
              <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                <Field label="Name">
                  <input
                    type="text"
                    value={at.name || ''}
                    onChange={(e) => {
                      const types = [...(config.appointment_types || [])];
                      const newName = e.target.value;
                      // Auto-generate the internal code from the display name so
                      // the clinic owner never has to think about developer slugs.
                      // We only regenerate when the existing code looks
                      // auto-generated (matches the previous slugified name) or
                      // is empty — preserves any custom code already in place.
                      const prev = types[idx] || {};
                      const prevSlug = slugifyTypeName(prev.name || '');
                      const shouldAutoCode = !prev.code || prev.code === prevSlug;
                      const nextCode = shouldAutoCode ? slugifyTypeName(newName) : prev.code;
                      types[idx] = { ...prev, name: newName, code: nextCode };
                      update('appointment_types', types);
                    }}
                    placeholder="Consultation"
                    className="input"
                  />
                </Field>
                <Field label="Duration (min)">
                  <input
                    type="number"
                    min="5"
                    max="480"
                    value={at.duration_minutes || 60}
                    onChange={(e) => {
                      const types = [...(config.appointment_types || [])];
                      types[idx] = { ...types[idx], duration_minutes: parseInt(e.target.value, 10) || 60 };
                      update('appointment_types', types);
                    }}
                    className="input"
                  />
                </Field>
                <Field label="Max Concurrent">
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={at.max_concurrent || 1}
                    onChange={(e) => {
                      const types = [...(config.appointment_types || [])];
                      types[idx] = { ...types[idx], max_concurrent: parseInt(e.target.value, 10) || 1 };
                      update('appointment_types', types);
                    }}
                    className="input"
                  />
                </Field>
              </div>
              <button
                type="button"
                onClick={() => {
                  const types = (config.appointment_types || []).filter((_, i) => i !== idx);
                  update('appointment_types', types);
                }}
                className="mt-6 p-1.5 text-gray-400 dark:text-gray-500 hover:text-red-500 transition-colors"
                title="Remove appointment type"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => {
              const types = [...(config.appointment_types || [])];
              types.push({ code: '', name: '', duration_minutes: 60, max_concurrent: 1 });
              update('appointment_types', types);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-primary-600 bg-primary-50 dark:bg-primary-900/20 rounded-lg hover:bg-primary-100 dark:hover:bg-primary-900/40 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Appointment Type
          </button>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">
            Tip: the internal short code is generated for you from the name.
            Existing custom codes are preserved.
          </p>
        </div>
      </Section>

      {/* ── Connections ── high-level connected/not-connected status. The
          Platform-managed integrations — no API keys needed from the user. */}
      <GoogleCalendarSection config={config} onUpdate={fetchConfig} />

      {/* ── Usage & Plan (includes platform-managed connection statuses) ── */}
      <UsagePlanSection />

      {/* Appointment Reminders */}
      <Section icon={Bell} title="Appointment Reminders">
        <p className="text-sm text-gray-500 dark:text-gray-400 -mt-2 mb-3">
          Automated SMS reminders sent before appointments. Patients can reply <strong>C</strong> to confirm,
          <strong> R</strong> to reschedule, or <strong>X</strong> to cancel — all handled by the AI agent.
        </p>
        <div className="space-y-4">
          <Toggle
            label="Appointment Reminder (2 hours before)"
            help="Send an SMS reminder 2 hours before the appointment."
            checked={config.reminder_settings?.['2h_enabled'] !== false}
            onChange={(v) =>
              update('reminder_settings', {
                ...(config.reminder_settings || {}),
                '2h_enabled': v,
              })
            }
          />
          <Toggle
            label="Confirmation Tracking"
            help="Track patient reply confirmations and show status on appointments."
            checked={config.reminder_settings?.confirmation_reply_enabled !== false}
            onChange={(v) =>
              update('reminder_settings', {
                ...(config.reminder_settings || {}),
                confirmation_reply_enabled: v,
              })
            }
          />
        </div>
      </Section>

      {/* Google Review Solicitation */}
      <Section icon={Star} title="Google Review Solicitation">
        <p className="text-sm text-gray-500 dark:text-gray-400 -mt-2 mb-3">
          Automatically send a friendly SMS asking patients to leave a Google review after their appointment.
          Only sent after the follow-up message, with a configurable delay.
        </p>
        <div className="space-y-4">
          <Toggle
            label="Enable Review Requests"
            help="When enabled, patients will receive a review request SMS after their appointment."
            checked={config.review_settings?.enabled === true}
            onChange={(v) =>
              update('review_settings', {
                ...(config.review_settings || {}),
                enabled: v,
              })
            }
          />
          {config.review_settings?.enabled && (
            <>
              <Field label="Google Review Link" help="Your Google Business profile review URL. Patients tap this link to leave a review.">
                <input
                  type="url"
                  value={config.review_settings?.google_review_link || ''}
                  onChange={(e) =>
                    update('review_settings', {
                      ...(config.review_settings || {}),
                      google_review_link: e.target.value,
                    })
                  }
                  placeholder="https://g.page/r/your-business/review"
                  className="input"
                />
              </Field>
              <Field label="Delay After Appointment (hours)" help="How many hours after the appointment to send the review request.">
                <input
                  type="number"
                  min="1"
                  max="168"
                  value={config.review_settings?.delay_hours || 24}
                  onChange={(e) =>
                    update('review_settings', {
                      ...(config.review_settings || {}),
                      delay_hours: parseInt(e.target.value, 10) || 24,
                    })
                  }
                  className="input"
                  style={{ maxWidth: '120px' }}
                />
              </Field>
              <Field
                label="Appointment Types for Reviews"
                help="Comma-separated list of appointment type keys. Leave empty to send for all types."
              >
                <input
                  type="text"
                  value={(config.review_settings?.appointment_types || []).join(', ')}
                  onChange={(e) =>
                    update('review_settings', {
                      ...(config.review_settings || {}),
                      appointment_types: e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="cleaning, checkup (leave empty for all)"
                  className="input"
                />
              </Field>
            </>
          )}
        </div>
      </Section>

      <style>{`
        .input {
          width: 100%;
          padding: 0.625rem 1rem;
          border: 1px solid #e5e7eb;
          border-radius: 0.5rem;
          font-size: 0.875rem;
          outline: none;
          background: white;
        }
        .input:focus {
          border-color: #14b8a6;
          box-shadow: 0 0 0 2px rgba(20,184,166,0.2);
        }
        .dark .input {
          background: #374151;
          border-color: #4b5563;
          color: #f3f4f6;
        }
        .dark .input:focus {
          border-color: #14b8a6;
          box-shadow: 0 0 0 2px rgba(20,184,166,0.3);
        }
      `}</style>
    </div>
  );
}

// ── Usage & Plan section ─────────────────────────────────────────────────────

function UsageBar({ label, used, limit, unit, color = 'primary' }) {
  const percent = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const remaining = Math.max(0, limit - used);
  const isWarning = percent >= 80;
  const isDanger = percent >= 95;
  const barColor = isDanger ? 'bg-red-500' : isWarning ? 'bg-amber-500' : `bg-${color}-500`;

  return (
    <div>
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {typeof used === 'number' && used % 1 !== 0 ? used.toFixed(1) : used} / {limit >= 99999 ? 'Unlimited' : limit} {unit}
        </span>
      </div>
      <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
        <div
          className={`h-2.5 rounded-full transition-all duration-500 ${isDanger ? 'bg-red-500' : isWarning ? 'bg-amber-500' : 'bg-primary-500'}`}
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
        {limit >= 99999 ? 'Unlimited' : `${typeof remaining === 'number' && remaining % 1 !== 0 ? remaining.toFixed(1) : remaining} ${unit} remaining`}
        {isWarning && !isDanger && ' — approaching limit'}
        {isDanger && ' — limit reached, overage may apply'}
      </p>
    </div>
  );
}

function UsagePlanSection() {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await apiFetch('/api/tenants/usage');
        if (!cancelled) setUsage(data);
      } catch {
        // Silently fail — endpoint may not exist on older backends
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const planLabels = {
    starter: 'Starter',
    professional: 'Professional',
    enterprise: 'Enterprise',
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
          <Bot className="w-5 h-5 text-primary-500" />
          Usage & Plan
        </h3>
        {usage && (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300 uppercase tracking-wide">
            {planLabels[usage.plan] || usage.plan}
          </span>
        )}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading usage...
        </div>
      ) : usage ? (
        <div className="space-y-4">
          <UsageBar
            label="Call Minutes"
            used={usage.calls.used}
            limit={usage.calls.limit}
            unit="min"
          />
          <UsageBar
            label="SMS Messages"
            used={usage.sms.used}
            limit={usage.sms.limit}
            unit="SMS"
          />
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Billing period started {new Date(usage.period_start).toLocaleDateString()}.
            Usage resets monthly. Contact support to upgrade your plan.
          </p>
        </div>
      ) : (
        <p className="text-sm text-gray-400">Usage data not available.</p>
      )}

      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Connections</h4>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-sm">
            <PhoneIcon className="w-4 h-4 text-gray-400" />
            <span className="text-gray-600 dark:text-gray-300">Voice Agent (Vapi)</span>
            <CheckCircle className="w-4 h-4 text-green-500 ml-auto" />
            <span className="text-xs text-green-600 dark:text-green-400">Managed by platform</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Mail className="w-4 h-4 text-gray-400" />
            <span className="text-gray-600 dark:text-gray-300">SMS (Twilio)</span>
            <CheckCircle className="w-4 h-4 text-green-500 ml-auto" />
            <span className="text-xs text-green-600 dark:text-green-400">Managed by platform</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Helper components ────────────────────────────────────────────────────────

function Section({ icon: Icon, title, children }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 md:p-6 space-y-4">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
        <Icon className="w-5 h-5 text-primary-500" />
        {title}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, help, children, className = '' }) {
  return (
    <div className={className}>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">{label}</label>
      {children}
      {help && <p className="text-xs text-gray-400 mt-1">{help}</p>}
    </div>
  );
}

// Convert a "YYYY-MM-DD" string into a local-time Date (no TZ shift) so the
// themed calendar lands on the same day the user typed. Returns null for
// empty/invalid strings so the picker shows its placeholder state.
function isoToLocalDate(iso) {
  if (!iso || typeof iso !== 'string') return null;
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

// Inverse of isoToLocalDate — formats a Date back to "YYYY-MM-DD" in local
// time. Used when persisting the picker's selection.
function localDateToIso(d) {
  if (!d) return '';
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${mo}-${day}`;
}

// Editor for tenant.holidays — array of {date: 'YYYY-MM-DD', name: string}.
// Normalizes (dedupes + sorts ascending) on every change so the persisted
// shape always matches what the backend expects.
function HolidaysEditor({ holidays, onChange }) {
  const [newDate, setNewDate] = useState('');
  const [newName, setNewName] = useState('');
  const [err, setErr] = useState(null);

  // Always render in chronological order — caller may pass unsorted data.
  const sorted = React.useMemo(() => {
    return [...(holidays || [])]
      .filter((h) => h && h.date)
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  }, [holidays]);

  function add() {
    setErr(null);
    const date = (newDate || '').trim();
    const name = (newName || '').trim();
    if (!date) {
      setErr('Pick a date.');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      setErr('Date must be YYYY-MM-DD.');
      return;
    }
    if (!name) {
      setErr('Give the holiday a name (e.g. "Christmas Day").');
      return;
    }
    // Dedupe by date — later add for same date wins on name.
    const next = [
      ...sorted.filter((h) => h.date !== date),
      { date, name },
    ].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    onChange(next);
    setNewDate('');
    setNewName('');
  }

  function remove(date) {
    onChange(sorted.filter((h) => h.date !== date));
  }

  function updateName(date, name) {
    onChange(
      sorted.map((h) => (h.date === date ? { ...h, name } : h))
    );
  }

  // Friendly display label — falls back to the raw ISO date if parsing fails.
  function fmtDate(iso) {
    try {
      // Parse as local date to avoid TZ off-by-one shifts.
      const [y, m, d] = iso.split('-').map((v) => parseInt(v, 10));
      const dt = new Date(y, m - 1, d);
      return dt.toLocaleDateString(undefined, {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return iso;
    }
  }

  // Today (local) — used to dim past entries so admins can spot stale rows.
  const todayIso = (() => {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  })();

  return (
    <div className="space-y-3">
      {/* Existing entries */}
      {sorted.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No holidays configured yet.</p>
      ) : (
        <div className="space-y-2">
          {sorted.map((h) => {
            const isPast = h.date < todayIso;
            return (
              <div
                key={h.date}
                className={`flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3 border border-gray-100 dark:border-gray-700 ${
                  isPast ? 'opacity-60' : ''
                }`}
              >
                <div className="sm:w-44 shrink-0">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">
                    {fmtDate(h.date)}
                  </div>
                  <div className="text-xs text-gray-400 font-mono">{h.date}</div>
                </div>
                <input
                  type="text"
                  value={h.name || ''}
                  onChange={(e) => updateName(h.date, e.target.value)}
                  className="flex-1 px-3 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                  placeholder="Holiday name"
                />
                <button
                  type="button"
                  onClick={() => remove(h.date)}
                  className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                  title="Remove holiday"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Add new row */}
      <div className="flex flex-col sm:flex-row sm:items-end gap-3 pt-2 border-t border-gray-100 dark:border-gray-700">
        <div className="sm:min-w-[12rem]">
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
            Date
          </label>
          <ThemedDatePicker
            value={isoToLocalDate(newDate)}
            onChange={(d) => setNewDate(localDateToIso(d))}
            onClear={() => setNewDate('')}
            placeholder="Pick a date"
            min={isoToLocalDate(todayIso)}
            accent="primary"
          />
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
            Holiday name
          </label>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                add();
              }
            }}
            placeholder='e.g. "Christmas Day", "Thanksgiving"'
            className="w-full px-3 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
          />
        </div>
        <button
          type="button"
          onClick={add}
          className="px-4 py-1.5 bg-primary-500 hover:bg-primary-600 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5"
        >
          <Plus className="w-4 h-4" />
          Add
        </button>
      </div>

      {err && (
        <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" />
          {err}
        </p>
      )}

      <p className="text-xs text-gray-400">
        Don't forget to click <span className="font-medium">Save Changes</span> at the top to apply.
      </p>
    </div>
  );
}

function VapiConnectionRow({ connected, onConnected }) {
  const { toast, confirm } = useModal();
  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState(null);
  const [okMsg, setOkMsg] = useState(null);

  async function handleConnect() {
    if (!apiKey.trim()) {
      setErr('Paste your Vapi API key first.');
      return;
    }
    setSubmitting(true);
    setErr(null);
    setOkMsg(null);
    try {
      const body = { api_key: apiKey.trim() };
      if (phoneNumberId.trim()) body.phone_number_id = phoneNumberId.trim();
      const data = await apiFetch('/api/integrations/vapi/connect', {
        method: 'POST',
        body,
      });
      setOkMsg(data.message || 'Connected!');
      setApiKey('');
      setPhoneNumberId('');
      // Give the user a second to see the success message before closing.
      setTimeout(() => {
        setOpen(false);
        setOkMsg(null);
        onConnected?.();
      }, 1500);
    } catch (e) {
      setErr(e.message || 'Connection failed.');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDisconnect() {
    const ok = await confirm({
      title: 'Disconnect Vapi?',
      message: 'Your phone agent will stop answering calls until reconnected.',
      confirmText: 'Disconnect',
      variant: 'danger',
    });
    if (!ok) return;
    setSubmitting(true);
    setErr(null);
    try {
      await apiFetch('/api/integrations/vapi/disconnect', { method: 'POST' });
      onConnected?.();
    } catch (e) {
      setErr(e.message || 'Disconnect failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className={`rounded-lg border ${
        connected
          ? 'bg-green-50/50 dark:bg-green-900/10 border-green-200 dark:border-green-800'
          : 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-700'
      }`}
    >
      <div className="flex items-center gap-3 p-3">
        <div
          className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
            connected
              ? 'bg-green-100 dark:bg-green-900/30 text-green-600'
              : 'bg-gray-200 dark:bg-gray-600 text-gray-500'
          }`}
        >
          <PhoneIcon className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-white">Vapi (Voice Calls)</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {connected
              ? 'Phone agent is live — your Vapi number is answering calls.'
              : 'Phone agent is not configured yet. Click "Connect" to provision one.'}
          </p>
        </div>
        {connected ? (
          <>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium shrink-0">
              <CheckCircle className="w-3 h-3" />
              Connected
            </span>
            <button
              type="button"
              onClick={handleDisconnect}
              disabled={submitting}
              className="text-xs font-medium text-red-600 dark:text-red-400 hover:underline shrink-0 disabled:opacity-50"
            >
              Disconnect
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="px-3 py-1.5 bg-primary-500 text-white rounded-lg text-xs font-medium hover:bg-primary-600 shrink-0 transition-colors"
          >
            {open ? 'Cancel' : 'Connect with Vapi'}
          </button>
        )}
      </div>

      {open && !connected && (
        <div className="border-t border-gray-200 dark:border-gray-700 p-4 space-y-3 bg-white/60 dark:bg-gray-800/60">
          <p className="text-xs text-gray-600 dark:text-gray-400">
            Paste your Vapi API key. We'll create a new assistant pre-configured
            with your greeting, voice, and business info. Get the key at{' '}
            <a
              href="https://dashboard.vapi.ai/account"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:underline"
            >
              dashboard.vapi.ai → Account → API Keys
            </a>.
          </p>
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Vapi API Key <span className="text-red-400">*</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="vapi_sk_..."
              className="input"
              autoComplete="off"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Vapi Phone Number ID (optional)
            </label>
            <input
              type="text"
              value={phoneNumberId}
              onChange={(e) => setPhoneNumberId(e.target.value)}
              placeholder="Leave blank to set up later"
              className="input"
            />
            <p className="text-[11px] text-gray-400 mt-1">
              Only needed if you've already bought a phone number on Vapi.
            </p>
          </div>
          {err && (
            <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg p-2.5 text-xs text-red-700 dark:text-red-400">
              {err}
            </div>
          )}
          {okMsg && (
            <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg p-2.5 text-xs text-green-700 dark:text-green-400 flex items-start gap-2">
              <CheckCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{okMsg}</span>
            </div>
          )}
          <button
            type="button"
            onClick={handleConnect}
            disabled={submitting || !apiKey.trim()}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50 transition-colors"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Provisioning your AI agent…
              </>
            ) : (
              'Provision Assistant'
            )}
          </button>
        </div>
      )}
    </div>
  );
}

function ConnectionStatusRow({ icon: Icon, label, connected, connectedText, notConnectedText }) {
  return (
    <div
      className={`flex items-center gap-3 p-3 rounded-lg border ${
        connected
          ? 'bg-green-50/50 dark:bg-green-900/10 border-green-200 dark:border-green-800'
          : 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-700'
      }`}
    >
      <div
        className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
          connected
            ? 'bg-green-100 dark:bg-green-900/30 text-green-600'
            : 'bg-gray-200 dark:bg-gray-600 text-gray-500'
        }`}
      >
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {connected ? connectedText : notConnectedText}
        </p>
      </div>
      {connected ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium shrink-0">
          <CheckCircle className="w-3 h-3" />
          Connected
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-200 dark:bg-gray-600 text-gray-600 dark:text-gray-300 rounded-full text-xs font-medium shrink-0">
          Not connected
        </span>
      )}
    </div>
  );
}

function IntegrationSection({
  icon: Icon,
  title,
  description,
  configured,
  accent,
  learnMore,
  children,
}) {
  const accentMap = {
    indigo: { bg: 'bg-indigo-50', border: 'border-indigo-200 dark:border-indigo-800', text: 'text-indigo-600', iconBg: 'bg-indigo-100 dark:bg-indigo-900/30' },
    emerald: { bg: 'bg-emerald-50', border: 'border-emerald-200 dark:border-emerald-800', text: 'text-emerald-600', iconBg: 'bg-emerald-100 dark:bg-emerald-900/30' },
    pink: { bg: 'bg-pink-50', border: 'border-pink-200 dark:border-pink-800', text: 'text-pink-600', iconBg: 'bg-pink-100 dark:bg-pink-900/30' },
  };
  const a = accentMap[accent] || accentMap.indigo;

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-xl border ${a.border} p-6 space-y-4`}>
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg ${a.iconBg} flex items-center justify-center shrink-0`}>
          <Icon className={`w-5 h-5 ${a.text}`} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h3>
            {configured ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium">
                <CheckCircle className="w-3 h-3" />
                Connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded-full text-xs font-medium">
                Not connected
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
          {learnMore && (
            <a
              href={learnMore}
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-flex items-center gap-1 text-xs font-medium ${a.text} hover:underline mt-1`}
            >
              <LinkIcon className="w-3 h-3" />
              {learnMore.replace(/^https?:\/\//, '')}
            </a>
          )}
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">{children}</div>
    </div>
  );
}

function GoogleCalendarSection({ config, onUpdate }) {
  const { toast, confirm } = useModal();
  const [disconnecting, setDisconnecting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const connected = config?.google_calendar_connected;
  const email = config?.google_calendar_email;

  async function handleConnect() {
    setConnecting(true);
    try {
      const data = await apiFetch('/api/integrations/google/connect');
      // Redirect browser to Google consent screen
      window.location.href = data.auth_url;
    } catch (err) {
      toast.error('Failed to start Google connection: ' + (err.message || err));
      setConnecting(false);
    }
  }

  async function handleDisconnect() {
    const ok = await confirm({
      title: 'Disconnect Google Calendar?',
      message: 'Your agent will fall back to the built-in scheduler until reconnected.',
      confirmText: 'Disconnect',
      variant: 'danger',
    });
    if (!ok) return;
    setDisconnecting(true);
    try {
      await apiFetch('/api/integrations/google/disconnect', { method: 'POST' });
      onUpdate(); // refresh config
    } catch (err) {
      toast.error('Failed to disconnect: ' + (err.message || err));
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-blue-200 dark:border-blue-800 p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center shrink-0">
          <CalendarCheck className="w-5 h-5 text-blue-600" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Google Calendar</h3>
            {connected ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium">
                <CheckCircle className="w-3 h-3" />
                Connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded-full text-xs font-medium">
                Not connected
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Connect your Google Calendar and the AI agent will
            check your real availability and book directly into your calendar.
          </p>
        </div>
      </div>

      {connected ? (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Mail className="w-4 h-4 text-blue-600" />
            <span className="text-sm font-medium text-gray-900 dark:text-white">{email}</span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Your AI agent is using this Google Calendar for availability checks and bookings.
            Appointments will appear directly in your calendar.
          </p>
          <button
            onClick={handleDisconnect}
            disabled={disconnecting}
            className="px-4 py-2 bg-white dark:bg-gray-800 border border-red-200 dark:border-red-700 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 transition-colors"
          >
            {disconnecting ? 'Disconnecting...' : 'Disconnect Google Calendar'}
          </button>
        </div>
      ) : (
        <div className="bg-gray-50 dark:bg-gray-700/50 border border-gray-100 dark:border-gray-700 rounded-lg p-4 space-y-3">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Click the button below to sign in with Google and grant calendar access.
            This is a one-time setup — no API keys needed.
          </p>
          <button
            onClick={handleConnect}
            disabled={connecting}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors shadow-sm"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            {connecting ? 'Redirecting...' : 'Connect Google Calendar'}
          </button>
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Requires the platform admin to have configured Google OAuth credentials.
          </p>
        </div>
      )}
    </div>
  );
}

function Toggle({ label, help, checked, onChange }) {
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className="mt-0.5 shrink-0"
        aria-label={label}
      >
        {checked ? (
          <ToggleRight className="w-8 h-8 text-primary-500" />
        ) : (
          <ToggleLeft className="w-8 h-8 text-gray-300 dark:text-gray-500" />
        )}
      </button>
      <div>
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</p>
        {help && <p className="text-xs text-gray-400 mt-0.5">{help}</p>}
      </div>
    </div>
  );
}

function SecretField({
  label,
  fieldKey,
  showSecrets,
  setShowSecrets,
  masked,
  value,
  onChange,
  placeholder,
}) {
  const visible = showSecrets[fieldKey];
  // If user has typed a new value, show what they typed; otherwise show masked from server
  const displayValue = value !== undefined && value !== null ? value : masked || '';

  return (
    <Field label={label}>
      <div className="relative">
        <input
          type={visible ? 'text' : 'password'}
          value={displayValue}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="input pr-10"
          autoComplete="off"
        />
        <button
          type="button"
          onClick={() =>
            setShowSecrets((prev) => ({ ...prev, [fieldKey]: !prev[fieldKey] }))
          }
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          aria-label={visible ? 'Hide' : 'Show'}
        >
          {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      <p className="text-xs text-gray-400 mt-1">
        {value
          ? 'New value will be saved.'
          : masked
          ? `Currently set (${masked}). Type to replace.`
          : 'Not set.'}
      </p>
    </Field>
  );
}
