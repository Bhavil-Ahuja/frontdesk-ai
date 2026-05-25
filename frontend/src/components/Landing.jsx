import React from 'react';
import { Link } from 'react-router-dom';
import {
  Sparkles,
  Phone,
  CalendarCheck,
  MessageSquare,
  Bot,
  Zap,
  ShieldCheck,
  ArrowRight,
  CheckCircle2,
} from 'lucide-react';

export default function Landing() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      {/* Top bar */}
      <header className="border-b border-gray-100 dark:border-gray-800">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 bg-primary-500 rounded-xl flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-gray-900 dark:text-white text-lg">Scheduler.ai</span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white px-3 py-2"
            >
              Sign in
            </Link>
            <Link
              to="/register"
              className="text-sm font-medium px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 py-20 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 rounded-full text-xs font-medium mb-6">
          <Zap className="w-3.5 h-3.5" />
          AI-Powered Voice Agents for Healthcare
        </div>
        <h1 className="text-5xl font-bold text-gray-900 dark:text-white leading-tight max-w-3xl mx-auto">
          Never miss a patient call <span className="text-primary-500">again</span>
        </h1>
        <p className="text-lg text-gray-500 dark:text-gray-400 mt-6 max-w-2xl mx-auto">
          Scheduler.ai answers your front desk calls 24/7, books appointments into your calendar,
          sends SMS reminders, and escalates emergencies — all automatically.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link
            to="/register"
            className="inline-flex items-center gap-2 px-6 py-3 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 transition-colors shadow-lg shadow-primary-500/30"
          >
            Register your business
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/login"
            className="inline-flex items-center gap-2 px-6 py-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Sign in to dashboard
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-6 py-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <Feature
            icon={Phone}
            title="24/7 Phone Coverage"
            description="Your AI receptionist answers every call instantly, even outside business hours."
          />
          <Feature
            icon={CalendarCheck}
            title="Smart Calendar Booking"
            description="Appointments are booked directly into your Google Calendar with conflict-free slot selection."
          />
          <Feature
            icon={MessageSquare}
            title="SMS Reminders"
            description="Automated 24-hour appointment reminders and post-visit follow-ups via Twilio."
          />
          <Feature
            icon={Bot}
            title="Custom Agent Persona"
            description="Configure your agent's name, voice, greeting, and knowledge base to match your brand."
          />
          <Feature
            icon={ShieldCheck}
            title="Smart Escalation"
            description="Emergency calls are automatically transferred to your on-call provider."
          />
          <Feature
            icon={Sparkles}
            title="Built for Healthcare"
            description="Dental, hospital, clinic, vet, physio — pick a vertical and we'll tune the prompt."
          />
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-4xl mx-auto px-6 py-16">
        <h2 className="text-3xl font-bold text-gray-900 dark:text-white text-center mb-12">How it works</h2>
        <div className="space-y-6">
          <Step
            number="1"
            title="Register your business"
            description="Tell us about your practice, choose a plan, and pick a URL slug."
          />
          <Step
            number="2"
            title="Wait for admin approval"
            description="Your account is reviewed (usually within 24 hours)."
          />
          <Step
            number="3"
            title="Connect your integrations"
            description="Link your Vapi account (for phone calls), Google Calendar (for bookings), and Twilio (for SMS)."
          />
          <Step
            number="4"
            title="Customize your agent"
            description="Set the greeting, business hours, knowledge base, and emergency rules."
          />
          <Step
            number="5"
            title="Go live"
            description="Your AI agent starts answering calls. Track every interaction in the dashboard."
          />
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-3xl mx-auto px-6 py-16 text-center">
        <div className="bg-gradient-to-br from-primary-500 to-primary-600 rounded-3xl p-12 text-white">
          <h2 className="text-3xl font-bold mb-3">Ready to stop missing calls?</h2>
          <p className="text-primary-50 text-lg mb-6">
            Get started in minutes — no credit card required.
          </p>
          <Link
            to="/register"
            className="inline-flex items-center gap-2 px-6 py-3 bg-white text-primary-600 rounded-lg text-sm font-semibold hover:bg-primary-50 transition-colors"
          >
            Register now
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </section>

      <footer className="border-t border-gray-100 dark:border-gray-800 mt-12">
        <div className="max-w-6xl mx-auto px-6 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
          © 2026 Scheduler.ai · AI receptionists for healthcare
        </div>
      </footer>
    </div>
  );
}

function Feature({ icon: Icon, title, description }) {
  return (
    <div className="p-6 rounded-2xl border border-gray-200 dark:border-gray-700 hover:border-primary-300 dark:hover:border-primary-700 hover:shadow-lg dark:hover:shadow-black/20 transition-all bg-white dark:bg-gray-800">
      <div className="w-10 h-10 rounded-lg bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 flex items-center justify-center mb-4">
        <Icon className="w-5 h-5" />
      </div>
      <h3 className="font-semibold text-gray-900 dark:text-white mb-2">{title}</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">{description}</p>
    </div>
  );
}

function Step({ number, title, description }) {
  return (
    <div className="flex items-start gap-4 p-5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="shrink-0 w-9 h-9 rounded-full bg-primary-500 text-white flex items-center justify-center font-bold text-sm">
        {number}
      </div>
      <div>
        <h3 className="font-semibold text-gray-900 dark:text-white">{title}</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{description}</p>
      </div>
    </div>
  );
}
