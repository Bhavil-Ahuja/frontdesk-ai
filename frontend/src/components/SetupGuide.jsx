import React, { useState, useEffect } from 'react';
import {
  Phone,
  CalendarCheck,
  MessageSquare,
  CheckCircle2,
  Circle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Settings,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { Link } from 'react-router-dom';

/**
 * SetupGuide — guided onboarding for new tenants.
 *
 * Under Option A (platform-managed SaaS), Vapi and Twilio are handled by
 * FrontDesk AI. The tenant only needs to:
 *   1. Configure business info & appointment types
 *   2. (Optional) Connect Google Calendar
 *   3. Wait for admin to provision their phone line
 *
 * No API keys, no Twilio accounts, no Vapi dashboards.
 */
export default function SetupGuide() {
  const { user, refreshUser } = useAuth();
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({ business: true, calendar: false, integrations: false });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await apiFetch('/api/config');
        if (!cancelled) setConfig(data);
      } catch (err) {
        console.error('Failed to load config:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const calendarConnected = config?.google_calendar_connected ?? false;
  const vapiConfigured = config?.vapi_configured ?? user?.vapi_configured ?? false;
  const twilioConfigured = config?.twilio_configured ?? user?.twilio_configured ?? false;
  const vapiEnabled = config?.vapi_enabled ?? true;
  const twilioEnabled = config?.twilio_enabled ?? true;

  // Steps the tenant actually needs to complete
  const steps = [
    {
      key: 'business',
      icon: Settings,
      title: 'Configure Your Business',
      done: true, // always "done" once they've registered
      shortDesc: 'Set up your business hours, appointment types, and agent personality.',
      details: [
        'Set your business hours so the AI knows when you\'re open',
        'Define appointment types (consultation, follow-up, etc.) with durations',
        'Customise your AI agent\'s name, greeting, and voice',
        'Add your knowledge base — FAQs, policies, directions',
      ],
      setupSteps: [
        {
          step: 'Open Agent Config',
          detail: 'Go to the Settings page and configure your business hours, appointment types, and agent details.',
        },
        {
          step: 'Customise your AI agent',
          detail: 'Set the agent name, greeting message, and voice. The AI will use these when answering calls.',
        },
        {
          step: 'Add knowledge base entries',
          detail: 'Add FAQs, insurance info, directions, and policies so the AI can answer patient questions accurately.',
        },
      ],
      bgColor: 'bg-blue-50 dark:bg-blue-900/30',
      borderColor: 'border-blue-200 dark:border-blue-800',
      iconColor: 'text-blue-600 dark:text-blue-400',
      iconBg: 'bg-blue-100 dark:bg-blue-900/30',
    },
    {
      key: 'calendar',
      icon: CalendarCheck,
      title: 'Connect Google Calendar',
      done: calendarConnected,
      shortDesc: 'One-click OAuth — lets the AI check availability and create bookings.',
      details: [
        'Lets the agent check your real-time availability before booking',
        'Creates actual calendar events (no double-bookings)',
        'Free, connects in one click — no API keys needed',
      ],
      setupSteps: [
        {
          step: 'Connect Google Calendar (Recommended)',
          detail: 'Go to Agent Config → Google Calendar section → click "Connect Google Calendar". One-click OAuth — no API keys needed.',
        },
        {
          step: 'Or use the built-in scheduler',
          detail: 'Without Google Calendar, the system uses your configured business hours to manage availability automatically.',
        },
      ],
      bgColor: 'bg-emerald-50 dark:bg-emerald-900/30',
      borderColor: 'border-emerald-200 dark:border-emerald-800',
      iconColor: 'text-emerald-600 dark:text-emerald-400',
      iconBg: 'bg-emerald-100 dark:bg-emerald-900/30',
    },
    // Only show integration step if at least one of Vapi/Twilio is enabled
    ...(vapiEnabled || twilioEnabled ? [{
      key: 'integrations',
      icon: Zap,
      title: `${vapiEnabled && twilioEnabled ? 'Phone & SMS' : vapiEnabled ? 'Voice Calls' : 'SMS'} (Managed by FrontDesk AI)`,
      done: (!vapiEnabled || vapiConfigured) && (!twilioEnabled || twilioConfigured),
      shortDesc: `${vapiEnabled ? 'Voice calls' : ''}${vapiEnabled && twilioEnabled ? ' and ' : ''}${twilioEnabled ? 'SMS' : ''} ${vapiEnabled && twilioEnabled ? 'are' : 'is'} handled by the platform — no setup needed from you.`,
      details: [
        ...(vapiEnabled ? ['Vapi (voice AI) is managed centrally by FrontDesk AI'] : []),
        ...(twilioEnabled ? ['Twilio (SMS) is managed centrally by FrontDesk AI'] : []),
        'Your dedicated phone number is assigned by the platform admin after approval',
        'No API keys, no third-party accounts to create — it just works',
      ],
      setupSteps: [
        {
          step: 'Nothing to do here!',
          detail: 'Once your account is approved, the platform admin will assign your dedicated phone number and voice assistant. You\'ll see them appear on your dashboard.',
        },
      ],
      bgColor: 'bg-violet-50 dark:bg-violet-900/30',
      borderColor: 'border-violet-200 dark:border-violet-800',
      iconColor: 'text-violet-600 dark:text-violet-400',
      iconBg: 'bg-violet-100 dark:bg-violet-900/30',
    }] : []),
  ];

  const requiredDone = calendarConnected || true; // Calendar is optional; business config is always "done"
  const allReady = (!vapiEnabled || vapiConfigured) && (!twilioEnabled || twilioConfigured);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 bg-primary-50 dark:bg-primary-900/30 rounded-xl flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-primary-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Welcome, {user?.business_name}!</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Let's get your AI voice agent set up. Most of the heavy lifting is done for you.
            </p>
          </div>
        </div>
      </div>

      {/* Progress banner */}
      <div
        className={`rounded-2xl border p-5 ${
          allReady
            ? 'bg-green-50 dark:bg-green-900/30 border-green-200 dark:border-green-800'
            : 'bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800'
        }`}
      >
        <div className="flex items-start gap-3">
          {allReady ? (
            <CheckCircle2 className="w-6 h-6 text-green-600 mt-0.5 shrink-0" />
          ) : (
            <AlertCircle className="w-6 h-6 text-amber-600 mt-0.5 shrink-0" />
          )}
          <div className="flex-1">
            <p
              className={`font-semibold ${
                allReady ? 'text-green-900 dark:text-green-400' : 'text-amber-900 dark:text-amber-400'
              }`}
            >
              {allReady
                ? 'You\'re ready to go live!'
                : 'Almost there — configure your business and wait for admin provisioning'}
            </p>
            <p
              className={`text-sm mt-1 ${
                allReady ? 'text-green-700 dark:text-green-400' : 'text-amber-700 dark:text-amber-400'
              }`}
            >
              {allReady
                ? 'All services are connected. Your AI agent can now answer calls, book appointments, and send SMS reminders.'
                : 'Set up your business info and calendar. Phone and SMS will be activated by the platform admin after your account is approved.'}
            </p>
            <div className="mt-3 flex items-center gap-3">
              <Link
                to="/settings"
                className="inline-flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                <Settings className="w-4 h-4" />
                Open Agent Config
              </Link>
              {allReady && (
                <Link
                  to="/"
                  className="inline-flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 transition-colors"
                >
                  Go to Dashboard
                  <ArrowRight className="w-4 h-4" />
                </Link>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Platform-managed banner — only show when at least one integration is enabled */}
      {(vapiEnabled || twilioEnabled) && (
        <div className="rounded-2xl border border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/20 p-4 flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 text-violet-600 dark:text-violet-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-violet-900 dark:text-violet-300">
              {vapiEnabled && twilioEnabled ? 'Phone & SMS are managed for you' : vapiEnabled ? 'Voice calls are managed for you' : 'SMS is managed for you'}
            </p>
            <p className="text-xs text-violet-700 dark:text-violet-400 mt-0.5">
              FrontDesk AI handles all {vapiEnabled ? 'Vapi (voice)' : ''}{vapiEnabled && twilioEnabled ? ' and ' : ''}{twilioEnabled ? 'Twilio (SMS)' : ''} infrastructure. You don't need to create
              accounts with these services or manage any API keys. Your dedicated phone number is assigned by
              the admin after account approval.
            </p>
          </div>
        </div>
      )}

      {/* Step cards */}
      <div className="space-y-4">
        {steps.map((step, stepIdx) => {
          const Icon = step.icon;
          const isOpen = expanded[step.key];
          return (
            <div
              key={step.key}
              className={`rounded-2xl border ${step.borderColor} bg-white dark:bg-gray-800 overflow-hidden`}
            >
              {/* Header */}
              <button
                onClick={() =>
                  setExpanded((prev) => ({
                    ...prev,
                    [step.key]: !prev[step.key],
                  }))
                }
                className="w-full p-5 flex items-center gap-4 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                {/* Step number */}
                <div
                  className={`w-12 h-12 rounded-xl ${step.iconBg} flex items-center justify-center shrink-0 relative`}
                >
                  <Icon className={`w-6 h-6 ${step.iconColor}`} />
                  <span className={`absolute -top-1 -left-1 w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center ${
                    step.done
                      ? 'bg-green-500 text-white'
                      : 'bg-gray-300 dark:bg-gray-600 text-gray-700 dark:text-gray-300'
                  }`}>
                    {step.done ? <CheckCircle2 className="w-3.5 h-3.5" /> : stepIdx + 1}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-gray-900 dark:text-white">{step.title}</h3>
                    {step.done ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        {step.key === 'integrations' ? 'Provisioned' : 'Done'}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded-full text-xs font-medium">
                        <Circle className="w-3 h-3" />
                        {step.key === 'integrations' ? 'Pending admin setup' : 'To do'}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{step.shortDesc}</p>
                </div>
                {isOpen ? (
                  <ChevronUp className="w-5 h-5 text-gray-400 shrink-0" />
                ) : (
                  <ChevronDown className="w-5 h-5 text-gray-400 shrink-0" />
                )}
              </button>

              {/* Expanded details */}
              {isOpen && (
                <div className={`border-t ${step.borderColor} ${step.bgColor} p-5 space-y-4`}>
                  {/* What it does */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">What this covers</h4>
                    <ul className="space-y-1.5">
                      {step.details.map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                          <CheckCircle2
                            className={`w-4 h-4 ${step.iconColor} mt-0.5 shrink-0`}
                          />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* How to set up */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                      {step.key === 'integrations' ? 'How it works' : 'How to set it up'}
                    </h4>
                    <ol className="space-y-3">
                      {step.setupSteps.map((s, idx) => (
                        <li key={idx} className="flex items-start gap-3">
                          <span
                            className={`shrink-0 w-6 h-6 rounded-full ${step.iconBg} ${step.iconColor} flex items-center justify-center text-xs font-bold`}
                          >
                            {step.key === 'integrations' ? <ShieldCheck className="w-3.5 h-3.5" /> : idx + 1}
                          </span>
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900 dark:text-white">{s.step}</p>
                            <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">{s.detail}</p>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>

                  {/* CTA — only for business and calendar steps */}
                  {step.key !== 'integrations' && (
                    <div className="pt-2">
                      <Link
                        to="/settings"
                        className="inline-flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                      >
                        <Settings className="w-4 h-4" />
                        {step.key === 'business' ? 'Open Agent Config' : 'Connect Calendar in Agent Config'}
                      </Link>
                    </div>
                  )}

                  {/* Integration status badges for the managed section */}
                  {step.key === 'integrations' && (
                    <div className="pt-2 space-y-2">
                      {vapiEnabled && (
                        <div className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                          <Phone className="w-4 h-4 text-indigo-500" />
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900 dark:text-white">Vapi Voice Agent</p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">Handles incoming calls and AI conversation</p>
                          </div>
                          {vapiConfigured ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium">
                              <CheckCircle2 className="w-3 h-3" /> Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded-full text-xs font-medium">
                              <Circle className="w-3 h-3" /> Awaiting setup
                            </span>
                          )}
                        </div>
                      )}
                      {twilioEnabled && (
                        <div className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                          <MessageSquare className="w-4 h-4 text-pink-500" />
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900 dark:text-white">Twilio SMS</p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">Appointment reminders and follow-up texts</p>
                          </div>
                          {twilioConfigured ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs font-medium">
                              <CheckCircle2 className="w-3 h-3" /> Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded-full text-xs font-medium">
                              <Circle className="w-3 h-3" /> Awaiting setup
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
