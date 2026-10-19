'use client';

import React from 'react';

export interface Employee {
  id?: number;
  full_name: string;
  title: string;
  seniority_level: 'executive' | 'management' | 'staff';
  linkedin_profile_url?: string;
  email?: string;
  location?: string;
  avatar_url?: string;
}

export interface OrgHierarchyProps {
  isOpen: boolean;
  onClose: () => void;
  companyName: string;
  linkedinUrl?: string;
  totalEmployees: number;
  tiers: {
    executive: Employee[];
    management: Employee[];
    staff: Employee[];
  };
}

export const OrgHierarchyModal: React.FC<OrgHierarchyProps> = ({
  isOpen,
  onClose,
  companyName,
  linkedinUrl,
  totalEmployees,
  tiers,
}) => {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-4xl max-h-[85vh] flex flex-col rounded-xl border border-slate-700/80 bg-slate-900 shadow-2xl overflow-hidden text-slate-100">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4 bg-slate-950/60">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🏢</span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-bold text-white tracking-wide">{companyName}</h3>
                <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-cyan-950/80 text-cyan-400 border border-cyan-800/60">
                  {totalEmployees} Employees
                </span>
              </div>
              {linkedinUrl && (
                <a
                  href={linkedinUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-cyan-400 hover:text-cyan-300 transition-colors inline-flex items-center gap-1 mt-0.5"
                >
                  Verified Corporate LinkedIn ↗
                </a>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            title="Close Modal"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Executive Tier */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <span className="px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider rounded bg-purple-950/80 text-purple-300 border border-purple-800/60">
                ⭐ Executive Leadership ({tiers.executive.length})
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {tiers.executive.map((emp, i) => (
                <EmployeeCard key={emp.id || i} employee={emp} />
              ))}
              {tiers.executive.length === 0 && (
                <p className="text-xs text-slate-500 italic col-span-2">No executives recorded.</p>
              )}
            </div>
          </section>

          {/* Management Tier */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <span className="px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider rounded bg-blue-950/80 text-blue-300 border border-blue-800/60">
                👔 Operational Management ({tiers.management.length})
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {tiers.management.map((emp, i) => (
                <EmployeeCard key={emp.id || i} employee={emp} />
              ))}
              {tiers.management.length === 0 && (
                <p className="text-xs text-slate-500 italic col-span-2">No managers recorded.</p>
              )}
            </div>
          </section>

          {/* Staff Tier */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <span className="px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider rounded bg-slate-800 text-slate-300 border border-slate-700">
                👥 Key Personnel & Staff ({tiers.staff.length})
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {tiers.staff.map((emp, i) => (
                <EmployeeCard key={emp.id || i} employee={emp} />
              ))}
              {tiers.staff.length === 0 && (
                <p className="text-xs text-slate-500 italic col-span-2">No staff recorded.</p>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

const EmployeeCard: React.FC<{ employee: Employee }> = ({ employee }) => {
  return (
    <div className="flex items-start gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/40 hover:border-slate-700 transition-colors">
      <div className="w-10 h-10 rounded-full bg-slate-800 overflow-hidden flex-shrink-0 flex items-center justify-center text-sm font-bold text-slate-400">
        {employee.avatar_url ? (
          <img src={employee.avatar_url} alt={employee.full_name} className="w-full h-full object-cover" />
        ) : (
          employee.full_name.charAt(0)
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-1">
          <h4 className="text-sm font-semibold text-slate-200 truncate">{employee.full_name}</h4>
          {employee.linkedin_profile_url && (
            <a
              href={employee.linkedin_profile_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-cyan-400 hover:underline flex-shrink-0"
            >
              Profile ↗
            </a>
          )}
        </div>
        <p className="text-xs text-slate-400 truncate mt-0.5">{employee.title}</p>
        {employee.location && (
          <p className="text-[11px] text-slate-500 truncate mt-0.5">📍 {employee.location}</p>
        )}
      </div>
    </div>
  );
};
