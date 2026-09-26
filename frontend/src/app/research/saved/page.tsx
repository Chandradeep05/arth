'use client';

import React, { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth/AuthProvider';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { Trash2, FileText, ChevronDown, ChevronUp, Calendar, Loader2 } from 'lucide-react';

interface SavedReportSummary {
  id: string;
  symbol: string;
  title: string;
  generated_at: string;
  data_as_of: string;
  engine_version: string;
  saved_at: string;
}

interface SavedReportDetail extends SavedReportSummary {
  report_content: any;
  sources: any[];
}

export default function SavedResearchPage() {
  const api = useAuthenticatedApi();
  const { loading: authLoading } = useAuth();
  const [reports, setReports] = useState<SavedReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<SavedReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (!authLoading && api.isAuthenticated) {
      fetchReports();
    } else if (!authLoading) {
      setLoading(false);
    }
  }, [authLoading, api.isAuthenticated]);

  const fetchReports = async () => {
    try {
      const data = await api.get<SavedReportSummary[]>('/api/v1/user/research/saved');
      if (data) {
        setReports(data);
      }
    } catch (error) {
      console.error('Failed to fetch saved reports', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchDetail = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    setDetailLoading(true);
    try {
      const data = await api.get<SavedReportDetail>(`/api/v1/user/research/saved/${id}`);
      if (data) {
        setExpandedDetail(data);
      }
    } catch (error) {
      console.error('Failed to fetch detail', error);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.delete(`/api/v1/user/research/saved/${id}`);
      setReports(reports.filter(r => r.id !== id));
      if (expandedId === id) setExpandedId(null);
    } catch (error) {
      console.error('Failed to delete report', error);
    }
  };

  if (loading) {
    return (
      <div className="p-8 text-[var(--text-dim)] font-mono text-xs">
        Loading saved research portfolio...
      </div>
    );
  }

  if (!api.isAuthenticated) {
    return (
      <div className="space-y-8 animate-fadeIn max-w-5xl">
        <div className="card text-center py-16">
          <FileText className="w-10 h-10 text-[var(--text-dim)] mx-auto mb-3 opacity-40" />
          <p className="text-sm font-medium text-[var(--text)]">Sign in to view saved reports</p>
          <p className="text-xs text-[var(--text-dim)] font-mono mt-1">
            Authentication is required to access your research portfolio.
          </p>
          <a
            href="/auth/login"
            className="inline-block mt-4 px-5 py-2 rounded-lg bg-[var(--accent)] text-black font-bold text-xs hover:opacity-90 transition-opacity"
          >
            Sign In
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fadeIn max-w-5xl">
      <div className="flex items-center gap-3">
        <FileText className="w-6 h-6 text-[var(--green)]" />
        <div>
          <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
            Saved Institutional Research
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-1 font-mono">
            Archived company teardowns, multi-factor models, and RAG-grounded reports
          </p>
        </div>
      </div>

      {reports.length === 0 ? (
        <div className="card text-center py-16">
          <FileText className="w-10 h-10 text-[var(--text-dim)] mx-auto mb-3 opacity-40" />
          <p className="text-sm font-medium text-[var(--text)]">No saved research reports</p>
          <p className="text-xs text-[var(--text-dim)] font-mono mt-1">Generate and save intelligence reports from the Research Lab.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {reports.map((report) => (
            <div key={report.id} className="card overflow-hidden">
              <div 
                className="p-4 md:p-5 cursor-pointer flex items-center justify-between hover:bg-[rgba(255,255,255,0.02)] transition-colors"
                onClick={() => fetchDetail(report.id)}
              >
                <div className="flex items-center gap-3.5">
                  <div className="w-10 h-10 rounded-full bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] flex items-center justify-center shrink-0">
                    <span className="font-mono text-xs font-bold text-white">{report.symbol.slice(0, 4)}</span>
                  </div>
                  <div>
                    <h3 className="font-heading text-sm font-semibold text-white">{report.title}</h3>
                    <div className="flex items-center gap-2 text-[11px] font-mono text-[var(--text-dim)] mt-0.5">
                      <Calendar className="w-3 h-3" />
                      {new Date(report.saved_at).toLocaleDateString()}
                      <span>•</span>
                      <span>Engine: {report.engine_version}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={(e) => handleDelete(e, report.id)}
                    className="p-1.5 text-[var(--text-dim)] hover:text-[var(--red)] hover:bg-[rgba(239,68,68,0.1)] rounded-full transition-colors cursor-pointer"
                    title="Delete Report"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  {expandedId === report.id ? (
                    <ChevronUp className="w-4 h-4 text-[var(--text-dim)]" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-[var(--text-dim)]" />
                  )}
                </div>
              </div>

              {expandedId === report.id && (
                <div className="border-t border-[var(--border)] bg-[rgba(0,0,0,0.3)] p-5">
                  {detailLoading ? (
                    <div className="flex items-center gap-2 text-xs font-mono text-[var(--text-dim)]">
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--green)]" /> Loading report contents...
                    </div>
                  ) : expandedDetail ? (
                    <div className="space-y-4">
                      <h4 className="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--text-muted)]">Report Content</h4>
                      <pre className="bg-[var(--surface-2)] p-4 rounded-xl border border-[var(--border)] text-xs font-mono text-[var(--text)] overflow-x-auto max-h-96">
                        {typeof expandedDetail.report_content === 'string' 
                          ? expandedDetail.report_content 
                          : JSON.stringify(expandedDetail.report_content, null, 2)}
                      </pre>
                      {expandedDetail.sources?.length > 0 && (
                        <div>
                          <h4 className="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Sources Referenced</h4>
                          <ul className="list-disc pl-5 text-xs font-mono text-[var(--text-dim)] space-y-1">
                            {expandedDetail.sources.map((s, i) => (
                              <li key={i}>{typeof s === 'string' ? s : JSON.stringify(s)}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-xs font-mono text-[var(--red)]">Failed to load report detail.</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
