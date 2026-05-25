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
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getToken } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
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

      // Fallback: use browser SpeechSynthesis
      if ('speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance(
          'Hi there! Thank you for calling. How can I help you today?'
        );
        utterance.rate = 0.95;
        utterance.pitch = 1.0;

        // Try to pick a voice that roughly matches
        const voices = window.speechSynthesis.getVoices();
        const voice = VOICE_OPTIONS.find((v) => v.id === voiceId);
        if (voice && voices.length > 0) {
          const isM = voice.description?.toLowerCase().includes('male') &&
                      !voice.description?.toLowerCase().includes('female');
          const match = voices.find((v) =>
            v.lang.startsWith('en') &&
            (isM ? v.name.toLowerCase().includes('male') : v.name.toLowerCase().includes('female'))
          ) || voices.find((v) => v.lang.startsWith('en'));
          if (match) utterance.voice = match;
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
    <div className="p-8 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between sticky top-0 bg-gray-50 dark:bg-gray-900 -mx-8 px-8 py-4 border-b border-gray-200 dark:border-gray-700 z-10">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Agent Configuration</h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1">Manage your AI receptionist settings</p>
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
            <input
              type="tel"
              value={config.business_phone || ''}
              onChange={(e) => update('business_phone', e.target.value)}
              placeholder="+1 (512) 555-0100"
              className="input"
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
          <Field label="Timezone">
            <input
              type="text"
              value={config.timezone || ''}
              onChange={(e) => update('timezone', e.target.value)}
              className="input"
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
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Agent Voice</label>
            <p className="text-xs text-gray-400 mb-3">Select a voice for your AI agent. Click the play button to preview each voice.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {VOICE_OPTIONS.map((v) => {
                const isSelected = (config.voice_id || VOICE_OPTIONS[0].id) === v.id;
                const isPlaying = playingVoiceId === v.id;
                const isLoading = loadingVoiceId === v.id;
                return (
                  <div
                    key={v.id}
                    onClick={() => update('voice_id', v.id)}
                    className={`relative flex items-start gap-3 p-3.5 rounded-xl border-2 cursor-pointer transition-all ${
                      isSelected
                        ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20 shadow-sm'
                        : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-sm'
                    }`}
                  >
                    {/* Radio indicator */}
                    <div className="mt-0.5 shrink-0">
                      <div
                        className={`w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors ${
                          isSelected ? 'border-primary-500' : 'border-gray-300 dark:border-gray-500'
                        }`}
                      >
                        {isSelected && (
                          <div className="w-2 h-2 rounded-full bg-primary-500" />
                        )}
                      </div>
                    </div>

                    {/* Voice info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-semibold ${isSelected ? 'text-primary-700 dark:text-primary-300' : 'text-gray-900 dark:text-white'}`}>
                          {v.name}
                        </span>
                        {isPlaying && (
                          <Volume2 className="w-3.5 h-3.5 text-primary-500 animate-pulse" />
                        )}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">{v.description}</p>
                    </div>

                    {/* Play/Stop button */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        playVoicePreview(v.id);
                      }}
                      className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                        isPlaying
                          ? 'bg-primary-500 text-white hover:bg-primary-600 shadow-md'
                          : isLoading
                          ? 'bg-gray-100 dark:bg-gray-700 text-gray-400'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-primary-100 dark:hover:bg-primary-900/30 hover:text-primary-600'
                      }`}
                      title={isPlaying ? 'Stop preview' : 'Play voice preview'}
                      disabled={isLoading}
                    >
                      {isLoading ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : isPlaying ? (
                        <Square className="w-3 h-3" />
                      ) : (
                        <Play className="w-3.5 h-3.5 ml-0.5" />
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Section>

      {/* Escalation */}
      <Section icon={PhoneIcon} title="Escalation & Emergencies">
        <div className="space-y-4">
          <Field
            label="Escalation Phone Number"
            help="When the AI escalates a call, it transfers to this number."
          >
            <input
              type="tel"
              value={config.escalation_phone || ''}
              onChange={(e) => update('escalation_phone', e.target.value)}
              placeholder="+1 (512) 555-0100"
              className="input"
            />
          </Field>
          <Field
            label="Emergency Guidance"
            help="Instructions the agent follows for medical emergencies."
          >
            <textarea
              value={config.emergency_guidance || ''}
              onChange={(e) => update('emergency_guidance', e.target.value)}
              rows={2}
              placeholder="If the caller mentions severe pain, swelling, or trauma, transfer immediately."
              className="input resize-none"
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
              <div key={day} className="flex items-center gap-4">
                <div className="w-24">
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
              <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-3">
                <Field label="Short Code">
                  <input
                    type="text"
                    value={at.code || ''}
                    onChange={(e) => {
                      const types = [...(config.appointment_types || [])];
                      types[idx] = { ...types[idx], code: e.target.value.toLowerCase().replace(/\s+/g, '_') };
                      update('appointment_types', types);
                    }}
                    placeholder="consultation"
                    className="input"
                  />
                </Field>
                <Field label="Display Name">
                  <input
                    type="text"
                    value={at.name || ''}
                    onChange={(e) => {
                      const types = [...(config.appointment_types || [])];
                      types[idx] = { ...types[idx], name: e.target.value };
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
        </div>
      </Section>

      {/* Vapi integration */}
      <IntegrationSection
        icon={PhoneIcon}
        title="Vapi (Voice Agent)"
        description="Required to receive phone calls. Get credentials at vapi.ai → Settings → API Keys."
        configured={config.vapi_configured}
        accent="indigo"
        learnMore="https://vapi.ai"
      >
        <SecretField
          label="Vapi API Key"
          fieldKey="vapi_api_key"
          showSecrets={showSecrets}
          setShowSecrets={setShowSecrets}
          masked={config.vapi_api_key_masked}
          value={config.vapi_api_key}
          onChange={(v) => update('vapi_api_key', v)}
          placeholder="vapi_sk_..."
        />
        <Field label="Vapi Assistant ID">
          <input
            type="text"
            value={config.vapi_assistant_id || ''}
            onChange={(e) => update('vapi_assistant_id', e.target.value)}
            placeholder="asst_..."
            className="input"
          />
        </Field>
        <Field label="Vapi Phone Number ID">
          <input
            type="text"
            value={config.vapi_phone_number_id || ''}
            onChange={(e) => update('vapi_phone_number_id', e.target.value)}
            placeholder="phone_..."
            className="input"
          />
        </Field>
      </IntegrationSection>

      {/* Google Calendar integration */}
      <GoogleCalendarSection config={config} onUpdate={fetchConfig} />

      {/* Twilio integration */}
      <IntegrationSection
        icon={Mail}
        title="Twilio (SMS)"
        description="Optional. Send SMS reminders & follow-ups. Get credentials at twilio.com → Console."
        configured={config.twilio_configured}
        accent="pink"
        learnMore="https://www.twilio.com"
      >
        <Field label="Twilio Account SID">
          <input
            type="text"
            value={config.twilio_account_sid || ''}
            onChange={(e) => update('twilio_account_sid', e.target.value)}
            placeholder="AC..."
            className="input"
          />
        </Field>
        <SecretField
          label="Twilio Auth Token"
          fieldKey="twilio_auth_token"
          showSecrets={showSecrets}
          setShowSecrets={setShowSecrets}
          masked={config.twilio_auth_token_masked}
          value={config.twilio_auth_token}
          onChange={(v) => update('twilio_auth_token', v)}
          placeholder="32-char auth token"
        />
        <Field label="Twilio SMS-from Phone">
          <input
            type="tel"
            value={config.twilio_phone_number || ''}
            onChange={(e) => update('twilio_phone_number', e.target.value)}
            placeholder="+15125550100"
            className="input"
          />
        </Field>
      </IntegrationSection>

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

// ── Helper components ────────────────────────────────────────────────────────

function Section({ icon: Icon, title, children }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
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
      alert('Failed to start Google connection: ' + (err.message || err));
      setConnecting(false);
    }
  }

  async function handleDisconnect() {
    if (!confirm('Disconnect Google Calendar? Your agent will fall back to the built-in scheduler.')) return;
    setDisconnecting(true);
    try {
      await apiFetch('/api/integrations/google/disconnect', { method: 'POST' });
      onUpdate(); // refresh config
    } catch (err) {
      alert('Failed to disconnect: ' + (err.message || err));
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
