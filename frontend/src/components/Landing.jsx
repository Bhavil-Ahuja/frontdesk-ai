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
} from 'lucide-react';
import ThemeToggle from './ThemeToggle';

export default function Landing() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white overflow-x-hidden">
      {/* Nav */}
      <header className="sticky top-0 z-50 border-b border-white/5 bg-[#0a0a0f]/80 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto px-5 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-500 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-white">FrontDesk AI</span>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/login"
              className="text-sm font-medium text-white/50 hover:text-white px-3 py-2 transition-colors"
            >
              Sign in
            </Link>
            <Link
              to="/register"
              className="text-sm font-semibold px-4 py-2 rounded-xl bg-indigo-500 text-white hover:bg-indigo-600 transition-colors btn-press"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative max-w-6xl mx-auto px-5 pt-20 pb-16 md:pt-28 md:pb-24 text-center overflow-hidden">
        {/* Decorative orbs */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-indigo-600/12 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-20 left-1/4 w-64 h-64 bg-indigo-500/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-20 right-1/4 w-64 h-64 bg-indigo-500/6 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 rounded-full text-xs font-medium mb-6">
            <Zap className="w-3.5 h-3.5" />
            AI-Powered Voice Agents for Any Business
          </div>

          <h1 className="text-4xl sm:text-5xl md:text-6xl font-extrabold leading-tight max-w-3xl mx-auto">
            Never miss a{' '}
            <span className="gradient-text">caller again</span>
          </h1>

          <p className="text-base md:text-lg text-white/50 mt-5 max-w-2xl mx-auto leading-relaxed">
            FrontDesk AI answers your front desk calls 24/7, books appointments into your calendar,
            sends SMS reminders, and escalates urgent calls — all automatically.
          </p>

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              to="/register"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold bg-indigo-500 text-white hover:bg-indigo-600 transition-colors btn-press"
            >
              Register your business
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link
              to="/login"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-white/10 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white text-sm font-medium transition-all btn-press"
            >
              Sign in to dashboard
            </Link>
          </div>

          {/* Stats */}
          <div className="mt-12 grid grid-cols-2 md:grid-cols-4 gap-4 max-w-2xl mx-auto">
            {[
              { n: '24/7', label: 'Always on' },
              { n: '< 2s', label: 'Answer time' },
              { n: '< 5%', label: 'Escalation rate' },
              { n: '∞', label: 'Concurrent calls' },
            ].map(s => (
              <div key={s.n} className="p-4 rounded-2xl bg-white/4 border border-white/8">
                <p className="text-2xl font-bold gradient-text">{s.n}</p>
                <p className="text-xs text-white/40 mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-5 py-12 md:py-16">
        <div className="text-center mb-10">
          <h2 className="text-2xl md:text-3xl font-bold">Everything your front desk needs</h2>
          <p className="text-white/40 mt-2 text-sm">One AI agent. Infinite availability.</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Feature icon={Phone}         title="24/7 Phone Coverage"      description="Your AI agent answers every call instantly, even outside business hours." />
          <Feature icon={CalendarCheck} title="Smart Calendar Booking"   description="Appointments booked directly into Google Calendar with conflict-free slot selection." />
          <Feature icon={MessageSquare} title="SMS Reminders"            description="Automated 24-hour appointment reminders and post-visit follow-ups via Exotel." />
          <Feature icon={Bot}           title="Custom Agent Persona"     description="Configure your agent's name, voice, greeting, and business info to match your brand." />
          <Feature icon={ShieldCheck}   title="Smart Escalation"         description="Urgent calls are automatically transferred to your on-call staff." />
          <Feature icon={Sparkles}      title="Built for Any Business"   description="Coaching institutes, clinics, salons — pick your vertical and we tune the agent." />
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-3xl mx-auto px-5 py-12 md:py-16">
        <h2 className="text-2xl md:text-3xl font-bold text-center mb-10">How it works</h2>
        <div className="space-y-3">
          {[
            { n: '1', title: 'Register your business',  desc: 'Tell us about your business, choose your vertical, and pick a URL slug.' },
            { n: '2', title: 'Wait for admin approval', desc: 'Your account is reviewed — usually within 24 hours.' },
            { n: '3', title: 'Connect integrations',    desc: 'Link Google Calendar for bookings and Exotel for SMS reminders.' },
            { n: '4', title: 'Customize your agent',    desc: 'Set the greeting, business hours, business info, and emergency rules.' },
            { n: '5', title: 'Go live',                  desc: 'Your AI agent starts answering calls. Track every interaction in the dashboard.' },
          ].map(s => (
            <div key={s.n} className="flex items-start gap-4 p-5 rounded-2xl border border-white/5 bg-white/3 hover:bg-white/5 transition-colors">
              <div className="shrink-0 w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-xs font-bold text-white">
                {s.n}
              </div>
              <div>
                <p className="font-semibold text-white">{s.title}</p>
                <p className="text-sm text-white/40 mt-0.5">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-3xl mx-auto px-5 py-12 md:py-16">
        <div className="relative rounded-2xl overflow-hidden p-8 md:p-12 text-center border border-indigo-500/20">
          <div className="absolute inset-0 bg-gradient-to-br from-indigo-600/15 via-indigo-500/5 to-indigo-600/10 pointer-events-none" />
          <div className="absolute inset-0 bg-[#0a0a0f]/60 pointer-events-none" />
          <div className="relative z-10">
            <h2 className="text-2xl md:text-3xl font-bold">Ready to stop missing calls?</h2>
            <p className="text-white/50 mt-2 mb-7">Get started in minutes — no credit card required.</p>
            <Link
              to="/register"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-indigo-500 text-white text-sm font-semibold hover:bg-indigo-600 transition-colors btn-press"
            >
              Register now
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-white/5 py-6 text-center text-sm text-white/20">
        © 2026 FrontDesk AI · AI agents for every business
      </footer>
    </div>
  );
}

function Feature({ icon: Icon, title, description }) {
  return (
    <div className="p-5 rounded-xl border border-white/5 bg-white/3 hover:bg-white/5 hover:border-white/10 transition-all card-hover">
      <div className="w-9 h-9 rounded-lg bg-indigo-500/15 flex items-center justify-center mb-4">
        <Icon className="w-4 h-4 text-indigo-400" />
      </div>
      <h3 className="font-semibold text-white text-sm mb-1.5">{title}</h3>
      <p className="text-sm text-white/40 leading-relaxed">{description}</p>
    </div>
  );
}
