import React, { useState, useEffect } from 'react';
import {
  BookOpen,
  Save,
  Plus,
  Trash2,
  CheckCircle,
  Building2,
  DollarSign,
  HelpCircle,
  Clock,
  StickyNote,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

export default function KnowledgeBase() {
  const [kb, setKb] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    fetchKB();
  }, []);

  async function fetchKB() {
    try {
      const data = await apiFetch('/api/knowledge');
      setKb(data || {});
    } catch (err) {
      console.error('Failed to load KB:', err);
    } finally {
      setLoading(false);
    }
  }

  async function saveKB() {
    setSaving(true);
    try {
      await apiFetch('/api/knowledge', { method: 'PUT', body: kb });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      console.error('Save failed:', err);
    } finally {
      setSaving(false);
    }
  }

  function updateOfficeField(field, value) {
    setKb({ ...kb, office_info: { ...kb.office_info, [field]: value } });
  }

  function updateService(index, field, value) {
    const updated = [...(kb.services || [])];
    updated[index] = { ...updated[index], [field]: field.includes('price') || field === 'duration_minutes' ? Number(value) : value };
    setKb({ ...kb, services: updated });
  }

  function addService() {
    setKb({
      ...kb,
      services: [
        ...(kb.services || []),
        { name: 'New Service', price_min: 0, price_max: 0, duration_minutes: 30, notes: '' },
      ],
    });
  }

  function removeService(index) {
    setKb({ ...kb, services: (kb.services || []).filter((_, i) => i !== index) });
  }

  function updateFaq(index, field, value) {
    const updated = [...(kb.faqs || [])];
    updated[index] = { ...updated[index], [field]: value };
    setKb({ ...kb, faqs: updated });
  }

  function addFaq() {
    setKb({
      ...kb,
      faqs: [...(kb.faqs || []), { question: 'New question?', answer: 'Answer here.' }],
    });
  }

  function removeFaq(index) {
    setKb({ ...kb, faqs: (kb.faqs || []).filter((_, i) => i !== index) });
  }

  if (loading || !kb) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6 md:mb-8">
        <div>
          <h2 className="text-xl md:text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <BookOpen className="w-6 md:w-7 h-6 md:h-7 text-primary-500" />
            Practice Info
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Edit information the AI agent uses to answer questions
          </p>
        </div>
        <button
          onClick={saveKB}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50 transition-colors"
        >
          {saved ? (
            <>
              <CheckCircle className="w-4 h-4" /> Saved!
            </>
          ) : (
            <>
              <Save className="w-4 h-4" /> {saving ? 'Saving...' : 'Save Changes'}
            </>
          )}
        </button>
      </div>

      {/* ── Office Information ────────────────────────────────────── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden mb-6">
        <div className="px-5 py-4 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-100 dark:border-blue-900/40">
          <h3 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Building2 className="w-5 h-5 text-blue-500" />
            Office Information
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            Basic details about your practice — address, phone, hours
          </p>
        </div>
        <div className="p-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(kb.office_info || {}).map(([key, value]) => (
              <div key={key}>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 capitalize">
                  {key.replace(/_/g, ' ')}
                </label>
                <input
                  type="text"
                  value={value}
                  onChange={(e) => updateOfficeField(key, e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Services & Pricing ────────────────────────────────────── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden mb-6">
        <div className="px-5 py-4 bg-emerald-50 dark:bg-emerald-900/20 border-b border-emerald-100 dark:border-emerald-900/40 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-emerald-500" />
              Services & Pricing
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Procedures you offer and their price ranges
            </p>
          </div>
          <button
            onClick={addService}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 rounded-lg hover:bg-emerald-200 dark:hover:bg-emerald-900/60 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> Add Service
          </button>
        </div>
        <div className="p-5">
          {(kb.services || []).length === 0 ? (
            <div className="text-center py-6">
              <DollarSign className="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
              <p className="text-sm text-gray-400 dark:text-gray-500">No services added yet. Click "Add Service" to get started.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {(kb.services || []).map((svc, i) => (
                <div
                  key={i}
                  className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg border border-gray-100 dark:border-gray-600/50"
                >
                  <input
                    type="text"
                    value={svc.name}
                    onChange={(e) => updateService(i, 'name', e.target.value)}
                    className="flex-1 px-2 py-1.5 border border-gray-200 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                    placeholder="Service name"
                  />
                  <div className="flex items-center gap-1.5">
                    <div className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
                      $
                      <input
                        type="number"
                        value={svc.price_min}
                        onChange={(e) => updateService(i, 'price_min', e.target.value)}
                        className="w-20 px-2 py-1.5 border border-gray-200 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                      />
                      –$
                      <input
                        type="number"
                        value={svc.price_max}
                        onChange={(e) => updateService(i, 'price_max', e.target.value)}
                        className="w-20 px-2 py-1.5 border border-gray-200 dark:border-gray-600 rounded text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                      />
                    </div>
                    {svc.duration_minutes !== undefined && (
                      <span className="flex items-center gap-0.5 text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap" title="Duration">
                        <Clock className="w-3 h-3" /> {svc.duration_minutes}m
                      </span>
                    )}
                    <button
                      onClick={() => removeService(i)}
                      className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded ml-1"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Frequently Asked Questions ────────────────────────────── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="px-5 py-4 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-100 dark:border-amber-900/40 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <HelpCircle className="w-5 h-5 text-amber-500" />
              Frequently Asked Questions
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Common questions the AI can answer for callers
            </p>
          </div>
          <button
            onClick={addFaq}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40 rounded-lg hover:bg-amber-200 dark:hover:bg-amber-900/60 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> Add FAQ
          </button>
        </div>
        <div className="p-5">
          {(kb.faqs || []).length === 0 ? (
            <div className="text-center py-6">
              <HelpCircle className="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
              <p className="text-sm text-gray-400 dark:text-gray-500">No FAQs added yet. Click "Add FAQ" to teach your AI common answers.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {(kb.faqs || []).map((faq, i) => (
                <div key={i} className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg border border-gray-100 dark:border-gray-600/50 space-y-2">
                  <div className="flex items-start gap-2">
                    <span className="mt-2 text-amber-400 dark:text-amber-500 text-sm font-bold">Q</span>
                    <input
                      type="text"
                      value={faq.question}
                      onChange={(e) => updateFaq(i, 'question', e.target.value)}
                      className="flex-1 px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm font-medium bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none"
                      placeholder="Question"
                    />
                    <button
                      onClick={() => removeFaq(i)}
                      className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="mt-2 text-blue-400 dark:text-blue-500 text-sm font-bold">A</span>
                    <textarea
                      value={faq.answer}
                      onChange={(e) => updateFaq(i, 'answer', e.target.value)}
                      rows={2}
                      className="flex-1 px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-primary-500 outline-none resize-none"
                      placeholder="Answer"
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
