import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Building2,
  User,
  Mail,
  Phone,
  Lock,
  Clock,
  AlertCircle,
  ArrowRight,
  Sparkles,
  MapPin,
  PhoneCall,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import ThemeToggle from './ThemeToggle';
import ThemedSelect from './ui/ThemedSelect';
import PhoneInput, { countryFromTimezone } from './ui/PhoneInput';
import { timezoneOptions } from '../lib/timezones';

const BUSINESS_TYPES = [
  { value: 'dental', label: 'Dental Office' },
  { value: 'hospital', label: 'Hospital' },
  { value: 'clinic', label: 'Clinic' },
  { value: 'veterinary', label: 'Veterinary' },
  { value: 'physiotherapy', label: 'Physiotherapy' },
  { value: 'custom', label: 'Other / Custom' },
];

// Full IANA timezone list — built lazily at module load from
// `Intl.supportedValuesOf('timeZone')` so the dropdown always matches what
// the browser will accept. Falls back to a curated static list for older
// browsers. The same options module is used everywhere timezone is picked.
const TIMEZONE_OPTIONS = timezoneOptions();

const INITIAL_FORM = {
  business_name: '',
  business_type: 'custom',
  business_address: '',
  google_maps_url: '',
  owner_name: '',
  owner_email: '',
  owner_phone: '',
  escalation_phone: '',
  password: '',
  password_confirm: '',
  timezone: 'America/Chicago',
};

export default function TenantRegister() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [form, setForm] = useState({ ...INITIAL_FORM });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [escalationSameAsPhone, setEscalationSameAsPhone] = useState(false);

  function updateField(field, value) {
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      // If "same as phone" is checked and we're updating owner_phone,
      // also update escalation_phone to stay in sync.
      if (field === 'owner_phone' && escalationSameAsPhone) {
        next.escalation_phone = value;
      }
      return next;
    });
  }

  function handleEscalationCheckbox(checked) {
    setEscalationSameAsPhone(checked);
    if (checked) {
      updateField('escalation_phone', form.owner_phone);
    }
  }

  function isValid() {
    const mapUrl = (form.google_maps_url || '').toLowerCase().trim();
    const mapUrlOk =
      mapUrl.startsWith('http') &&
      mapUrl.length >= 10 &&
      (
        (mapUrl.includes('google') && mapUrl.includes('map')) ||
        mapUrl.includes('goo.gl/maps') ||
        mapUrl.includes('maps.app.goo.gl')
      );
    return (
      form.business_name.length >= 2 &&
      form.business_address.length >= 5 &&
      mapUrlOk &&
      form.owner_name.length >= 2 &&
      form.owner_email.includes('@') &&
      form.owner_phone.length >= 5 &&
      form.escalation_phone.length >= 5 &&
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

      // Register + auto-login (slug is generated server-side)
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

  const inputClass =
    'w-full px-4 py-2.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none';
  const inputWithIconClass =
    'w-full pl-10 pr-4 py-2.5 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none';
  const labelClass = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5';

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 via-gray-50 to-blue-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-900 py-12 px-4 relative">
      {/* Theme toggle */}
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>

      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <Link
            to="/"
            className="inline-flex items-center gap-2 mb-6 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
          >
            ← Back to home
          </Link>
          <div className="mx-auto w-14 h-14 bg-primary-500 rounded-2xl flex items-center justify-center mb-4 shadow-lg shadow-primary-500/30">
            <Sparkles className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Get Started with FrontDesk AI</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-2 max-w-xl mx-auto">
            Register your business to get an AI-powered voice agent that handles scheduling,
            reminders, and patient calls 24/7.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
              <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
            </div>
          )}

          {/* Business Information */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <Building2 className="w-5 h-5 text-primary-500" />
              Business Information
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>
                  Business Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={form.business_name}
                  onChange={(e) => updateField('business_name', e.target.value)}
                  placeholder="Sunrise Clinic"
                  required
                  minLength={2}
                  className={inputClass}
                />
              </div>

              <div>
                <label className={labelClass}>
                  Business Type
                </label>
                <ThemedSelect
                  value={form.business_type}
                  onChange={(v) => updateField('business_type', v)}
                  options={BUSINESS_TYPES}
                />
              </div>

              <div className="md:col-span-2">
                <label className={labelClass}>
                  Timezone <span className="text-red-400">*</span>
                </label>
                <ThemedSelect
                  value={form.timezone}
                  onChange={(v) => updateField('timezone', v)}
                  icon={Clock}
                  options={TIMEZONE_OPTIONS}
                  searchable
                  searchPlaceholder="Search timezones..."
                />
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  Timezone is permanent — choose carefully. It can't be changed
                  after registration.
                </p>
              </div>

              <div className="md:col-span-2">
                <label className={labelClass}>
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
                    className={inputWithIconClass}
                  />
                </div>
              </div>

              <div className="md:col-span-2">
                <label className={labelClass}>
                  Google Maps Link <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="url"
                    value={form.google_maps_url}
                    onChange={(e) => updateField('google_maps_url', e.target.value)}
                    placeholder="https://maps.app.goo.gl/…  or  https://www.google.com/maps/place/…"
                    required
                    minLength={10}
                    maxLength={2048}
                    className={inputWithIconClass}
                  />
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  Paste a Google Maps share link to your clinic. Used by admins to
                  verify your location and shared with patients in SMS/email
                  reminders. Open Google Maps → search for your clinic → tap
                  "Share" → "Copy link".
                </p>
              </div>
            </div>
          </div>

          {/* Owner Contact */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <User className="w-5 h-5 text-primary-500" />
              Owner / Contact
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>
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
                    className={inputWithIconClass}
                  />
                </div>
              </div>

              <div>
                <label className={labelClass}>
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
                    className={inputWithIconClass}
                  />
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  This will be your login email
                </p>
              </div>

              <div className="md:col-span-2">
                <label className={labelClass}>
                  Phone <span className="text-red-400">*</span>
                </label>
                <PhoneInput
                  value={form.owner_phone}
                  onChange={(v) => updateField('owner_phone', v)}
                  defaultCountry={countryFromTimezone(form.timezone)}
                  placeholder="(512) 555-0100"
                  required
                  icon={Phone}
                />
              </div>
            </div>
          </div>

          {/* Escalation — required so emergencies always have a live human fallback */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <PhoneCall className="w-5 h-5 text-primary-500" />
              Emergency Escalation
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 -mt-2">
              When a caller has a medical emergency or asks for a human, the AI will
              transfer the call to this number. This is required so emergencies always
              reach a live person.
            </p>

            <div>
              <div className="flex items-center gap-2 mb-3">
                <input
                  type="checkbox"
                  id="escalation-same"
                  checked={escalationSameAsPhone}
                  onChange={(e) => handleEscalationCheckbox(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-primary-500 focus:ring-primary-500"
                />
                <label htmlFor="escalation-same" className="text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
                  Same as owner phone number
                </label>
              </div>

              <label className={labelClass}>
                Escalation Phone Number <span className="text-red-400">*</span>
              </label>
              <PhoneInput
                value={form.escalation_phone}
                onChange={(v) => {
                  setEscalationSameAsPhone(false);
                  updateField('escalation_phone', v);
                }}
                defaultCountry={countryFromTimezone(form.timezone)}
                placeholder="(512) 555-0200"
                required
                disabled={escalationSameAsPhone}
                icon={PhoneCall}
              />
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                Usually your front desk or on-call provider. You can add custom
                emergency guidance text later from the Agent Config page.
              </p>
            </div>
          </div>

          {/* Password */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-5">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <Lock className="w-5 h-5 text-primary-500" />
              Create a Password
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>
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
                    className={inputWithIconClass}
                  />
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Minimum 8 characters</p>
              </div>

              <div>
                <label className={labelClass}>
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
                    className={`w-full pl-10 pr-4 py-2.5 border rounded-lg text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 outline-none ${
                      passwordsMatch
                        ? 'border-gray-200 dark:border-gray-600 focus:ring-primary-500 focus:border-primary-500'
                        : 'border-red-300 dark:border-red-600 focus:ring-red-500 focus:border-red-500'
                    }`}
                  />
                </div>
                {!passwordsMatch && (
                  <p className="text-xs text-red-500 mt-1">Passwords do not match</p>
                )}
              </div>
            </div>
          </div>

          {/* What happens next */}
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
            <div className="flex items-start gap-3">
              <Clock className="w-5 h-5 text-blue-500 dark:text-blue-400 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-blue-900 dark:text-blue-300">What happens after I register?</p>
                <ol className="text-sm text-blue-700 dark:text-blue-400 mt-1 space-y-1 list-decimal list-inside">
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
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Already have an account?{' '}
              <Link to="/login" className="font-medium text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300">
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
