import React, { useState, useEffect } from 'react';
import {
  BookOpen,
  Save,
  Plus,
  Trash2,
  MessageSquare,
  Send,
  CheckCircle,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

export default function KnowledgeBase() {
  const [kb, setKb] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testQuestion, setTestQuestion] = useState('');
  const [testAnswer, setTestAnswer] = useState('');
  const [testing, setTesting] = useState(false);

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

  async function testKB() {
    if (!testQuestion.trim()) return;
    setTesting(true);
    setTestAnswer('');
    try {
      // Simple pattern match against FAQs for demo
      const q = testQuestion.toLowerCase();
      const match = kb?.faqs?.find(
        (faq) =>
          faq.question.toLowerCase().includes(q) ||
          q.includes(faq.question.toLowerCase().split(' ').slice(0, 3).join(' '))
      );
      if (match) {
        setTestAnswer(match.answer);
      } else {
        // Check services
        const svc = kb?.services?.find((s) => q.includes(s.name.toLowerCase()));
        if (svc) {
          setTestAnswer(
            `${svc.name}: $${svc.price_min}–$${svc.price_max}. Duration: ${svc.duration_minutes} minutes. ${svc.notes || ''}`
          );
        } else {
          setTestAnswer(
            "I'd be happy to help with that! Let me connect you with our team for the most accurate answer. Is there anything else I can help with?"
          );
        }
      }
    } finally {
      setTesting(false);
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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-dental-500"></div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Knowledge Base</h2>
          <p className="text-gray-500 mt-1">
            Edit information the AI agent uses to answer questions
          </p>
        </div>
        <button
          onClick={saveKB}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 bg-dental-500 text-white rounded-lg text-sm font-medium hover:bg-dental-600 disabled:opacity-50 transition-colors"
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

      {/* Office Info */}
      <Section title="Office Information" icon={BookOpen}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Object.entries(kb.office_info || {}).map(([key, value]) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-500 mb-1 capitalize">
                {key.replace(/_/g, ' ')}
              </label>
              <input
                type="text"
                value={value}
                onChange={(e) => updateOfficeField(key, e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-dental-500 focus:border-dental-500 outline-none"
              />
            </div>
          ))}
        </div>
      </Section>

      {/* Insurance */}
      <Section title="Insurance">
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Accepted Providers (comma-separated)
            </label>
            <input
              type="text"
              value={(kb.insurance?.accepted_providers || []).join(', ')}
              onChange={(e) =>
                setKb({
                  ...kb,
                  insurance: {
                    ...kb.insurance,
                    accepted_providers: e.target.value.split(',').map((s) => s.trim()),
                  },
                })
              }
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-dental-500 focus:border-dental-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Financing</label>
            <input
              type="text"
              value={kb.insurance?.financing || ''}
              onChange={(e) =>
                setKb({ ...kb, insurance: { ...kb.insurance, financing: e.target.value } })
              }
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-dental-500 focus:border-dental-500 outline-none"
            />
          </div>
        </div>
      </Section>

      {/* Services & Pricing */}
      <Section
        title="Services & Pricing"
        action={
          <button
            onClick={addService}
            className="flex items-center gap-1 text-xs text-dental-600 hover:text-dental-700"
          >
            <Plus className="w-3.5 h-3.5" /> Add Service
          </button>
        }
      >
        <div className="space-y-3">
          {(kb.services || []).map((svc, i) => (
            <div
              key={i}
              className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg"
            >
              <input
                type="text"
                value={svc.name}
                onChange={(e) => updateService(i, 'name', e.target.value)}
                className="flex-1 px-2 py-1.5 border border-gray-200 rounded text-sm bg-white focus:ring-2 focus:ring-dental-500 outline-none"
                placeholder="Service name"
              />
              <div className="flex items-center gap-1 text-sm text-gray-500">
                $
                <input
                  type="number"
                  value={svc.price_min}
                  onChange={(e) => updateService(i, 'price_min', e.target.value)}
                  className="w-20 px-2 py-1.5 border border-gray-200 rounded text-sm bg-white focus:ring-2 focus:ring-dental-500 outline-none"
                />
                –$
                <input
                  type="number"
                  value={svc.price_max}
                  onChange={(e) => updateService(i, 'price_max', e.target.value)}
                  className="w-20 px-2 py-1.5 border border-gray-200 rounded text-sm bg-white focus:ring-2 focus:ring-dental-500 outline-none"
                />
              </div>
              <button
                onClick={() => removeService(i)}
                className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </Section>

      {/* FAQs */}
      <Section
        title="Frequently Asked Questions"
        action={
          <button
            onClick={addFaq}
            className="flex items-center gap-1 text-xs text-dental-600 hover:text-dental-700"
          >
            <Plus className="w-3.5 h-3.5" /> Add FAQ
          </button>
        }
      >
        <div className="space-y-4">
          {(kb.faqs || []).map((faq, i) => (
            <div key={i} className="p-4 bg-gray-50 rounded-lg space-y-2">
              <div className="flex items-start gap-2">
                <input
                  type="text"
                  value={faq.question}
                  onChange={(e) => updateFaq(i, 'question', e.target.value)}
                  className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm font-medium bg-white focus:ring-2 focus:ring-dental-500 outline-none"
                  placeholder="Question"
                />
                <button
                  onClick={() => removeFaq(i)}
                  className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              <textarea
                value={faq.answer}
                onChange={(e) => updateFaq(i, 'answer', e.target.value)}
                rows={2}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:ring-2 focus:ring-dental-500 outline-none resize-none"
                placeholder="Answer"
              />
            </div>
          ))}
        </div>
      </Section>

      {/* Test Panel */}
      <div className="bg-dental-50 rounded-xl border border-dental-200 p-6">
        <h3 className="text-lg font-semibold text-dental-800 flex items-center gap-2 mb-4">
          <MessageSquare className="w-5 h-5" />
          Test Agent Response
        </h3>
        <div className="flex gap-3">
          <input
            type="text"
            value={testQuestion}
            onChange={(e) => setTestQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && testKB()}
            placeholder="Type a patient question..."
            className="flex-1 px-4 py-2.5 border border-dental-200 rounded-lg text-sm bg-white focus:ring-2 focus:ring-dental-500 outline-none"
          />
          <button
            onClick={testKB}
            disabled={testing}
            className="px-4 py-2.5 bg-dental-500 text-white rounded-lg text-sm font-medium hover:bg-dental-600 disabled:opacity-50 transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        {testAnswer && (
          <div className="mt-4 p-4 bg-white rounded-lg border border-dental-200">
            <p className="text-xs font-medium text-dental-600 mb-1">Sarah would respond:</p>
            <p className="text-sm text-gray-700">{testAnswer}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, icon: Icon, action, children }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          {Icon && <Icon className="w-5 h-5 text-dental-500" />}
          {title}
        </h3>
        {action}
      </div>
      {children}
    </div>
  );
}
