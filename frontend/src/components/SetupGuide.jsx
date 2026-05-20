import React, { useState, useEffect } from 'react';
import {
  Phone,
  CalendarCheck,
  MessageSquare,
  CheckCircle2,
  Circle,
  AlertCircle,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Settings,
  Sparkles,
  ArrowRight,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { Link } from 'react-router-dom';

/**
 * SetupGuide — guided onboarding for new tenants.
 * Shows the 3 integrations (Vapi / Calendar / Twilio) with explanations,
 * what's configured, what's not, and links to set them up.
 */
export default function SetupGuide() {
  const { user, refreshUser } = useAuth();
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({ vapi: true, calendar: false, twilio: false });

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

  const integrations = [
    {
      key: 'vapi',
      icon: Phone,
      title: 'Vapi (Voice Agent)',
      configured: config?.vapi_configured ?? user?.vapi_configured ?? false,
      shortDesc: 'Required — handles all incoming phone calls.',
      whatItDoes: [
        'Receives every patient call to your business phone number',
        'Lets the AI agent talk naturally with the caller',
        'Records call audio + transcript for your dashboard',
      ],
      howToSetup: [
        {
          step: 'Create a Vapi account',
          detail: 'Sign up at vapi.ai (free tier available).',
          link: 'https://vapi.ai',
        },
        {
          step: 'Get your API key',
          detail: 'Dashboard → Settings → API Keys → copy the private key.',
        },
        {
          step: 'Buy or import a phone number',
          detail: 'Vapi Dashboard → Phone Numbers → Buy or BYO Twilio number.',
        },
        {
          step: 'Paste credentials in Agent Config',
          detail: 'Open Agent Config below and enter your Vapi API key + phone number ID.',
        },
      ],
      bgColor: 'bg-indigo-50',
      borderColor: 'border-indigo-200',
      iconColor: 'text-indigo-600',
      iconBg: 'bg-indigo-100',
    },
    {
      key: 'calendar',
      icon: CalendarCheck,
      title: 'Calendar (Booking)',
      configured: config?.google_calendar_connected ?? false,
      shortDesc: 'Connect Google Calendar (free, 1-click) or use the built-in scheduler.',
      whatItDoes: [
        'Lets the agent check available slots in real time',
        'Creates actual bookings in your calendar (no double-bookings)',
        'Google Calendar: free, connects with one click — no API keys needed',
      ],
      howToSetup: [
        {
          step: 'Connect Google Calendar (Recommended)',
          detail: 'Go to Agent Config → Google Calendar section → click "Connect Google Calendar". One-click OAuth — no API keys needed.',
        },
        {
          step: 'Or skip it',
          detail: 'Without Google Calendar, the built-in scheduler uses your Business Hours to manage availability automatically.',
        },
      ],
      bgColor: 'bg-emerald-50',
      borderColor: 'border-emerald-200',
      iconColor: 'text-emerald-600',
      iconBg: 'bg-emerald-100',
    },
    {
      key: 'twilio',
      icon: MessageSquare,
      title: 'Twilio (SMS Reminders)',
      configured: config?.twilio_configured ?? user?.twilio_configured ?? false,
      shortDesc: 'Optional but recommended — SMS reminders & follow-ups.',
      whatItDoes: [
        'Sends 24-hour appointment reminder texts',
        'Sends post-visit follow-up messages',
        'Sends emergency escalation alerts to your on-call provider',
      ],
      howToSetup: [
        {
          step: 'Create a Twilio account',
          detail: 'Sign up at twilio.com — free trial credit included.',
          link: 'https://www.twilio.com',
        },
        {
          step: 'Buy an SMS-capable phone number',
          detail: 'Twilio Console → Phone Numbers → Buy a number with SMS enabled.',
        },
        {
          step: 'Get your Account SID and Auth Token',
          detail: 'Twilio Console → Account dashboard → copy both values.',
        },
        {
          step: 'Paste credentials in Agent Config',
          detail: 'Open Agent Config and enter Twilio SID, auth token, and SMS-from number.',
        },
      ],
      bgColor: 'bg-pink-50',
      borderColor: 'border-pink-200',
      iconColor: 'text-pink-600',
      iconBg: 'bg-pink-100',
    },
  ];

  const configuredCount = integrations.filter((i) => i.configured).length;
  const requiredCount = 2; // Vapi + Calendar are required
  const requiredConfigured = integrations.slice(0, 2).filter((i) => i.configured).length;
  const allReady = requiredConfigured === requiredCount;

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
          <div className="w-10 h-10 bg-primary-50 rounded-xl flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-primary-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Welcome, {user?.business_name}!</h1>
            <p className="text-sm text-gray-500">
              Let's get your AI voice agent set up. It takes about 10 minutes.
            </p>
          </div>
        </div>
      </div>

      {/* Progress banner */}
      <div
        className={`rounded-2xl border p-5 ${
          allReady
            ? 'bg-green-50 border-green-200'
            : 'bg-amber-50 border-amber-200'
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
                allReady ? 'text-green-900' : 'text-amber-900'
              }`}
            >
              {allReady
                ? 'You\'re ready to go live!'
                : `${requiredConfigured} of ${requiredCount} required integrations configured`}
            </p>
            <p
              className={`text-sm mt-1 ${
                allReady ? 'text-green-700' : 'text-amber-700'
              }`}
            >
              {allReady
                ? 'All required services are connected. Your AI agent can now answer calls and book appointments.'
                : 'Connect Vapi (for phone calls) and a calendar (Google Calendar or built-in scheduler) to activate your agent. Twilio is optional.'}
            </p>
            <div className="mt-3 flex items-center gap-3">
              <Link
                to="/settings"
                className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
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

      {/* Integration cards */}
      <div className="space-y-4">
        {integrations.map((integration) => {
          const Icon = integration.icon;
          const isOpen = expanded[integration.key];
          return (
            <div
              key={integration.key}
              className={`rounded-2xl border ${integration.borderColor} bg-white overflow-hidden`}
            >
              {/* Header */}
              <button
                onClick={() =>
                  setExpanded((prev) => ({
                    ...prev,
                    [integration.key]: !prev[integration.key],
                  }))
                }
                className="w-full p-5 flex items-center gap-4 text-left hover:bg-gray-50 transition-colors"
              >
                <div
                  className={`w-12 h-12 rounded-xl ${integration.iconBg} flex items-center justify-center shrink-0`}
                >
                  <Icon className={`w-6 h-6 ${integration.iconColor}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-gray-900">{integration.title}</h3>
                    {integration.configured ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs font-medium">
                        <Circle className="w-3 h-3" />
                        Not connected
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-0.5">{integration.shortDesc}</p>
                </div>
                {isOpen ? (
                  <ChevronUp className="w-5 h-5 text-gray-400 shrink-0" />
                ) : (
                  <ChevronDown className="w-5 h-5 text-gray-400 shrink-0" />
                )}
              </button>

              {/* Expanded details */}
              {isOpen && (
                <div className={`border-t ${integration.borderColor} ${integration.bgColor} p-5 space-y-4`}>
                  {/* What it does */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2">What it does</h4>
                    <ul className="space-y-1.5">
                      {integration.whatItDoes.map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm text-gray-700">
                          <CheckCircle2
                            className={`w-4 h-4 ${integration.iconColor} mt-0.5 shrink-0`}
                          />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* How to set up */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2">
                      How to set it up
                    </h4>
                    <ol className="space-y-3">
                      {integration.howToSetup.map((s, idx) => (
                        <li key={idx} className="flex items-start gap-3">
                          <span
                            className={`shrink-0 w-6 h-6 rounded-full ${integration.iconBg} ${integration.iconColor} flex items-center justify-center text-xs font-bold`}
                          >
                            {idx + 1}
                          </span>
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900">{s.step}</p>
                            <p className="text-xs text-gray-600 mt-0.5">{s.detail}</p>
                            {s.link && (
                              <a
                                href={s.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={`inline-flex items-center gap-1 text-xs font-medium ${integration.iconColor} hover:underline mt-1`}
                              >
                                {s.link}
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>

                  {/* CTA */}
                  <div className="pt-2">
                    <Link
                      to="/settings"
                      className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
                    >
                      <Settings className="w-4 h-4" />
                      Configure {integration.title.split(' ')[0]} in Agent Config
                    </Link>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
