import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Building2,
  User,
  Mail,
  Phone,
  Lock,
  Clock,
  CreditCard,
  AlertCircle,
  ArrowRight,
  Sparkles,
  MapPin,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const BUSINESS_TYPES = [
  { value: 'dental', label: 'Dental Office' },
  { value: 'hospital', label: 'Hospital' },
  { value: 'clinic', label: 'Clinic' },
  { value: 'veterinary', label: 'Veterinary' },
  { value: 'physiotherapy', label: 'Physiotherapy' },
  { value: 'custom', label: 'Other / Custom' },
];

const PLAN_TIERS = [
  {
    value: 'starter',
    label: 'Starter',
    price: '$49/mo',
    description: 'Up to 200 calls/month, 1 phone line',
  },
  {
    value: 'professional',
    label: 'Professional',
    price: '$149/mo',
    description: 'Up to 1,000 calls/month, 3 phone lines, SMS reminders',
  },
  {
    value: 'enterprise',
    label: 'Enterprise',
    price: 'Custom',
    description: 'Unlimited calls, dedicated support, custom integrations',
  },
];

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Phoenix',
  'America/Anchorage',
  'Pacific/Honolulu',
  'America/Toronto',
  'America/Vancouver',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Australia/Sydney',
];

const INITIAL_FORM = {
  slug: '',
  business_name: '',
  business_type: 'custom',
  business_address: '',
  owner_name: '',
  owner_email: '',
  owner_phone: '',
  password: '',
  password_confirm: '',
  timezone: 'America/Chicago',
  plan: 'starter',
};

export default function TenantRegister() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [form, setForm] = useState({ ...INITIAL_FORM });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [slugTouched, setSlugTouched] = useState(false);

  function updateField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  // Auto-generate slug from business name unless manually edited
  function handleBusinessNameChange(value) {
    updateField('business_name', value);
    if (!slugTouched) {
      const autoSlug = value
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, '')
        .trim()
        .replace(/\s+/g, '-')
        .slice(0, 100);
      updateField('slug', autoSlug);
    }
  }

  function handleSlugChange(value) {
    setSlugTouched(true);
    updateField('slug', value.toLowerCase().replace(/[^a-z0-9_-]/g, ''));
  }

  function isValid() {
    return (
      form.slug.length >= 2 &&
      form.business_name.length >= 2 &&
      form.business_address.length >= 5 &&
      form.owner_name.length >= 2 &&
      form.owner_email.includes('@') &&
      form.owner_phone.length >= 5 &&
      form.password.length >= 8 &&
      form.password === form.password_confirm
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!isValid()) return;

    setSubmitting(true);
    setError(null);

    try {
      const payload = { ...form };
      delete payload.password_confirm;

      // Register + auto-login
      const user = await register(payload);

      // Newly registered users are PENDING — go to waiting page
      if (user.status === 'PENDING') {
        navigate('/pending', { replace: true });
      } else {
        navigate('/setup', { replace: true });
      }
    } catch (err) {
      setError(err.message || 'Registration failed.');
    } finally {
      setSubmitting(false);
    }
  }

  const passwordsMatch =
    form.password.length === 0 || form.password === form.password_confirm;

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 via-gray-50 to-blue-50 py-12 px-4">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <Link
            to="/"
            className="inline-flex items-center gap-2 mb-6 text-sm text-gray-500 hover:text-gray-700"
          >
            ← Back to home
          </Link>
          <div className="mx-auto w-14 h-14 bg-primary-500 rounded-2xl flex items-center justify-center mb-4 shadow-lg shadow-primary-500/30">
            <Sparkles className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900">Get Started with Scheduler.ai</h1>
          <p className="text-gray-500 mt-2 max-w-xl mx-auto">
            Register your business to get an AI-powered voice agent that handles scheduling,
            reminders, and patient calls 24/7.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {/* Business Information */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Building2 className="w-5 h-5 text-primary-500" />
              Business Information
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Business Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={form.business_name}
                  onChange={(e) => handleBusinessNameChange(e.target.value)}
                  placeholder="Sunrise Clinic"
                  required
                  minLength={2}
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  URL Slug <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={form.slug}
                  onChange={(e) => handleSlugChange(e.target.value)}
                  placeholder="sunrise-clinic"
                  required
                  minLength={2}
                  maxLength={100}
                  pattern="^[a-z0-9_-]+$"
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Lowercase letters, numbers, hyphens only
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Business Type
                </label>
                <select
                  value={form.business_type}
                  onChange={(e) => updateField('business_type', e.target.value)}
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                >
                  {BUSINESS_TYPES.map((bt) => (
                    <option key={bt.value} value={bt.value}>
                      {bt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Timezone <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <Clock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <select
                    value={form.timezone}
                    onChange={(e) => updateField('timezone', e.target.value)}
                    required
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  >
                    {TIMEZONES.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Business Address <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    value={form.business_address}
                    onChange={(e) => updateField('business_address', e.target.value)}
                    placeholder="123 Main St, Suite 100, Austin, TX 78701"
                    required
                    minLength={5}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Owner Contact */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <User className="w-5 h-5 text-primary-500" />
              Owner / Contact
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Full Name <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    value={form.owner_name}
                    onChange={(e) => updateField('owner_name', e.target.value)}
                    placeholder="Dr. Jane Smith"
                    required
                    minLength={2}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Email <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="email"
                    value={form.owner_email}
                    onChange={(e) => updateField('owner_email', e.target.value)}
                    placeholder="jane@sunrise-clinic.com"
                    required
                    autoComplete="email"
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  />
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  This will be your login email
                </p>
              </div>

              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Phone <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="tel"
                    value={form.owner_phone}
                    onChange={(e) => updateField('owner_phone', e.target.value)}
                    placeholder="+1 (512) 555-0100"
                    required
                    minLength={5}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Password */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Lock className="w-5 h-5 text-primary-500" />
              Create a Password
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Password <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="password"
                    value={form.password}
                    onChange={(e) => updateField('password', e.target.value)}
                    placeholder="At least 8 characters"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                  />
                </div>
                <p className="text-xs text-gray-400 mt-1">Minimum 8 characters</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Confirm Password <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="password"
                    value={form.password_confirm}
                    onChange={(e) => updateField('password_confirm', e.target.value)}
                    placeholder="Re-enter password"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className={`w-full pl-10 pr-4 py-2.5 border rounded-lg text-sm focus:ring-2 outline-none ${
                      passwordsMatch
                        ? 'border-gray-200 focus:ring-primary-500 focus:border-primary-500'
                        : 'border-red-300 focus:ring-red-500 focus:border-red-500'
                    }`}
                  />
                </div>
                {!passwordsMatch && (
                  <p className="text-xs text-red-500 mt-1">Passwords do not match</p>
                )}
              </div>
            </div>
          </div>

          {/* Plan Selection */}
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <CreditCard className="w-5 h-5 text-primary-500" />
              Choose a Plan
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {PLAN_TIERS.map((plan) => (
                <button
                  key={plan.value}
                  type="button"
                  onClick={() => updateField('plan', plan.value)}
                  className={`text-left p-4 rounded-xl border-2 transition-all ${
                    form.plan === plan.value
                      ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold text-gray-900">{plan.label}</span>
                    <span
                      className={`text-sm font-bold ${
                        form.plan === plan.value ? 'text-primary-600' : 'text-gray-500'
                      }`}
                    >
                      {plan.price}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">{plan.description}</p>
                </button>
              ))}
            </div>
          </div>

          {/* What happens next */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
            <div className="flex items-start gap-3">
              <Clock className="w-5 h-5 text-blue-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-blue-900">What happens after I register?</p>
                <ol className="text-sm text-blue-700 mt-1 space-y-1 list-decimal list-inside">
                  <li>Your account is created and submitted for admin review</li>
                  <li>An admin approves you (usually within 24 hours)</li>
                  <li>You'll be guided through connecting Vapi, Google Calendar, and Twilio</li>
                  <li>Your AI agent goes live and starts answering calls</li>
                </ol>
              </div>
            </div>
          </div>

          {/* Submit */}
          <div className="flex items-center justify-between gap-4 pt-2">
            <p className="text-sm text-gray-500">
              Already have an account?{' '}
              <Link to="/login" className="font-medium text-primary-600 hover:text-primary-700">
                Sign in
              </Link>
            </p>
            <button
              type="submit"
              disabled={!isValid() || submitting}
              className="flex items-center gap-2 px-6 py-3 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-lg shadow-primary-500/30"
            >
              {submitting ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  Submitting...
                </>
              ) : (
                <>
                  Create Account
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
