'use client'

import React, { useState, useEffect } from 'react';
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
  const [reports, setReports] = useState<SavedReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<SavedReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    fetchReports();
  }, []);

  const fetchReports = async () => {
    try {
      const res = await api.get('/api/v1/user/research/saved');
      if (res.ok) {
        setReports(await res.json());
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
      const res = await api.get(`/api/v1/user/research/saved/${id}`);
      if (res.ok) {
        setExpandedDetail(await res.json());
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
      const res = await api.delete(`/api/v1/user/research/saved/${id}`);
      if (res.ok) {
        setReports(reports.filter(r => r.id !== id));
        if (expandedId === id) setExpandedId(null);
      }
    } catch (error) {
      console.error('Failed to delete report', error);
    }
  };

  if (loading) return <div className="p-8 text-zinc-400">Loading saved research...</div>;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <FileText className="w-8 h-8 text-blue-500" />
          <h1 className="text-3xl font-bold">Saved Research</h1>
        </div>

        {reports.length === 0 ? (
          <div className="text-center py-20 bg-zinc-900/50 rounded-2xl border border-zinc-800 border-dashed">
            <FileText className="w-12 h-12 text-zinc-700 mx-auto mb-4" />
            <p className="text-zinc-400 text-lg">No saved reports yet.</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {reports.map((report) => (
              <div key={report.id} className="bg-zinc-900 rounded-xl border border-zinc-800 overflow-hidden transition-colors hover:border-zinc-700">
                <div 
                  className="p-4 md:p-6 cursor-pointer flex items-center justify-between"
                  onClick={() => fetchDetail(report.id)}
                >
                  <div className="flex items-center gap-4">
                    <div className="bg-zinc-950 px-3 py-2 rounded-lg border border-zinc-800 flex flex-col items-center justify-center min-w-[70px]">
                      <span className="text-lg font-bold text-white">{report.symbol}</span>
                    </div>
                    <div>
                      <h3 className="font-semibold text-lg">{report.title}</h3>
                      <div className="flex items-center gap-2 text-sm text-zinc-500 mt-1">
                        <Calendar className="w-3.5 h-3.5" />
                        {new Date(report.saved_at).toLocaleDateString()}
                        <span>•</span>
                        <span>Engine: {report.engine_version}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <button
                      onClick={(e) => handleDelete(e, report.id)}
                      className="p-2 text-zinc-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                    >
                      <Trash2 className="w-5 h-5" />
                    </button>
                    {expandedId === report.id ? <ChevronUp className="w-5 h-5 text-zinc-400" /> : <ChevronDown className="w-5 h-5 text-zinc-400" />}
                  </div>
                </div>

                {expandedId === report.id && (
                  <div className="border-t border-zinc-800 bg-zinc-950/50 p-6">
                    {detailLoading ? (
                      <div className="flex items-center gap-2 text-zinc-400">
                        <Loader2 className="w-4 h-4 animate-spin" /> Loading report contents...
                      </div>
                    ) : expandedDetail ? (
                      <div className="space-y-4">
                        <h4 className="font-medium text-zinc-300">Report Content Preview</h4>
                        <pre className="bg-zinc-950 p-4 rounded-lg border border-zinc-800 text-xs text-zinc-400 overflow-x-auto max-h-96">
                          {JSON.stringify(expandedDetail.report_content, null, 2)}
                        </pre>
                        {expandedDetail.sources?.length > 0 && (
                          <div>
                            <h4 className="font-medium text-zinc-300 mb-2">Sources</h4>
                            <ul className="list-disc pl-5 text-sm text-zinc-400 space-y-1">
                              {expandedDetail.sources.map((s, i) => (
                                <li key={i}>{typeof s === 'string' ? s : JSON.stringify(s)}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-red-400">Failed to load report detail.</div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
