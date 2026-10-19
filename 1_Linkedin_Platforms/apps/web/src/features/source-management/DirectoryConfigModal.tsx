'use client';

import React, { useState } from 'react';

export interface PlatformConfig {
  id?: number;
  name: string;
  url_template: string;
  category: string;
  is_active: number;
}

interface DirectoryConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  platforms: PlatformConfig[];
  onSave: (platform: PlatformConfig) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

export const DirectoryConfigModal: React.FC<DirectoryConfigModalProps> = ({
  isOpen,
  onClose,
  platforms,
  onSave,
  onDelete,
}) => {
  const [name, setName] = useState('');
  const [urlTemplate, setUrlTemplate] = useState('');
  const [category, setCategory] = useState('General');
  const [isActive, setIsActive] = useState(1);
  const [editId, setEditId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !urlTemplate.trim()) return;
    setSaving(true);
    try {
      await onSave({
        id: editId || undefined,
        name: name.trim(),
        url_template: urlTemplate.trim(),
        category: category.trim(),
        is_active: isActive,
      });
      resetForm();
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setName('');
    setUrlTemplate('');
    setCategory('General');
    setIsActive(1);
    setEditId(null);
  };

  const handleEdit = (p: PlatformConfig) => {
    setEditId(p.id || null);
    setName(p.name);
    setUrlTemplate(p.url_template);
    setCategory(p.category || 'General');
    setIsActive(p.is_active);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-3xl max-h-[85vh] flex flex-col rounded-xl border border-slate-700 bg-slate-900 shadow-2xl overflow-hidden text-slate-100">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4 bg-slate-950/60">
          <div className="flex items-center gap-2">
            <span className="text-xl">⚙️</span>
            <h3 className="text-base font-bold text-white tracking-wide uppercase">
              Directory Platforms Configuration
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Add / Edit Form */}
          <form onSubmit={handleSubmit} className="p-4 rounded-lg border border-slate-800 bg-slate-950/50 space-y-3">
            <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
              {editId ? '✏️ Edit Platform Template' : '➕ Add Directory Platform'}
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Platform Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Treatwell, Airbnb, Yelp"
                  className="w-full px-3 py-1.5 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-purple-500"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Category / Sector</label>
                <input
                  type="text"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g. Salons, Hospitality, Directory"
                  className="w-full px-3 py-1.5 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                URL Search Template (<code className="text-purple-400">&#123;query&#125;</code>, <code className="text-purple-400">&#123;city&#125;</code>)
              </label>
              <input
                type="text"
                value={urlTemplate}
                onChange={(e) => setUrlTemplate(e.target.value)}
                placeholder="https://www.fresha.com/search?query={query}&address={city}"
                className="w-full px-3 py-1.5 text-xs font-mono rounded bg-slate-900 border border-slate-700 text-slate-200 focus:outline-none focus:border-purple-500"
                required
              />
            </div>
            <div className="flex items-center justify-between pt-2">
              <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isActive === 1}
                  onChange={(e) => setIsActive(e.target.checked ? 1 : 0)}
                  className="rounded border-slate-700 text-purple-600 focus:ring-0"
                />
                Active in Directory Scout runs
              </label>
              <div className="flex gap-2">
                {editId && (
                  <button
                    type="button"
                    onClick={resetForm}
                    className="px-3 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700"
                  >
                    Cancel
                  </button>
                )}
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-1.5 text-xs font-semibold rounded bg-purple-600 text-white hover:bg-purple-500 transition-colors disabled:opacity-50"
                >
                  {saving ? 'Saving...' : '💾 Save Platform'}
                </button>
              </div>
            </div>
          </form>

          {/* Existing Platforms Table */}
          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Configured Platforms</h4>
            <div className="rounded-lg border border-slate-800 overflow-hidden">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-3">Platform</th>
                    <th className="p-3">Category</th>
                    <th className="p-3">Template</th>
                    <th className="p-3">Status</th>
                    <th className="p-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 bg-slate-900/40">
                  {platforms.map((p) => (
                    <tr key={p.id} className="hover:bg-slate-800/30">
                      <td className="p-3 font-semibold text-white">{p.name}</td>
                      <td className="p-3 text-slate-400">{p.category}</td>
                      <td className="p-3 font-mono text-[11px] text-slate-400 max-w-xs truncate" title={p.url_template}>
                        {p.url_template}
                      </td>
                      <td className="p-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            p.is_active ? 'bg-emerald-950 text-emerald-400' : 'bg-slate-800 text-slate-500'
                          }`}
                        >
                          {p.is_active ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                      <td className="p-3 text-right space-x-2">
                        <button
                          onClick={() => handleEdit(p)}
                          className="text-purple-400 hover:text-purple-300 font-medium"
                        >
                          Edit
                        </button>
                        {p.id && (
                          <button
                            onClick={() => onDelete(p.id!)}
                            className="text-rose-400 hover:text-rose-300 font-medium"
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
