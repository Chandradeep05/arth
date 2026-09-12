'use client'

import React, { useState, useEffect } from 'react';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { useAuth } from '@/lib/auth/AuthProvider';
import { Users, Key, Copy, Check, ShieldAlert, Plus, ShieldX } from 'lucide-react';

interface User {
  id: string;
  email: string;
  role: 'user' | 'admin';
  access_status: 'active' | 'suspended' | 'pending';
  last_login: string | null;
  created_at: string;
}

interface InviteCode {
  id: string;
  code: string;
  max_uses: number | null;
  used_count: number;
  created_at: string;
}

export default function AdminPage() {
  const api = useAuthenticatedApi();
  const { user } = useAuth();
  
  const [users, setUsers] = useState<User[]>([]);
  const [inviteCodes, setInviteCodes] = useState<InviteCode[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [newCodeMaxUses, setNewCodeMaxUses] = useState<string>('');
  const [justGeneratedCode, setJustGeneratedCode] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role === 'admin') {
      fetchData();
    } else {
      setLoading(false);
    }
  }, [user]);

  const fetchData = async () => {
    try {
      const [usersRes, codesRes] = await Promise.all([
        api.get('/api/v1/admin/users'),
        api.get('/api/v1/admin/invite-codes')
      ]);
      if (usersRes.ok) setUsers(await usersRes.json());
      if (codesRes.ok) setInviteCodes(await codesRes.json());
    } catch (error) {
      console.error('Failed to fetch admin data', error);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateRole = async (userId: string, newRole: 'user' | 'admin') => {
    try {
      const res = await api.patch(`/api/v1/admin/users/${userId}/role`, { role: newRole });
      if (res.ok) {
        setUsers(users.map(u => u.id === userId ? { ...u, role: newRole } : u));
      }
    } catch (error) {
      console.error('Failed to update role', error);
    }
  };

  const handleUpdateStatus = async (userId: string, newStatus: 'active' | 'suspended' | 'pending') => {
    try {
      const res = await api.patch(`/api/v1/admin/users/${userId}/status`, { access_status: newStatus });
      if (res.ok) {
        setUsers(users.map(u => u.id === userId ? { ...u, access_status: newStatus } : u));
      }
    } catch (error) {
      console.error('Failed to update status', error);
    }
  };

  const handleGenerateCode = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = newCodeMaxUses ? { max_uses: parseInt(newCodeMaxUses) } : {};
      const res = await api.post('/api/v1/admin/invite-codes', payload);
      if (res.ok) {
        const data = await res.json();
        setJustGeneratedCode(data.code);
        setNewCodeMaxUses('');
        fetchData();
      }
    } catch (error) {
      console.error('Failed to generate code', error);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCode(text);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  if (loading) return <div className="p-8 text-zinc-400">Loading admin dashboard...</div>;

  if (user?.role !== 'admin') {
    return (
      <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col items-center justify-center p-4">
        <ShieldX className="w-16 h-16 text-red-500 mb-4" />
        <h1 className="text-2xl font-bold mb-2">Access Denied</h1>
        <p className="text-zinc-400">You must be an administrator to view this page.</p>
      </div>
    );
  }

  const stats = {
    total: users.length,
    active: users.filter(u => u.access_status === 'active').length,
    pending: users.filter(u => u.access_status === 'pending').length,
    suspended: users.filter(u => u.access_status === 'suspended').length,
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-4 md:p-8 space-y-8">
      <div className="max-w-6xl mx-auto space-y-8">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-8 h-8 text-purple-500" />
          <h1 className="text-3xl font-bold">Admin Dashboard</h1>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Users', value: stats.total },
            { label: 'Active', value: stats.active, color: 'text-green-400' },
            { label: 'Pending', value: stats.pending, color: 'text-yellow-400' },
            { label: 'Suspended', value: stats.suspended, color: 'text-red-400' },
          ].map((stat, i) => (
            <div key={i} className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl">
              <div className="text-zinc-500 text-sm font-medium mb-1">{stat.label}</div>
              <div className={`text-2xl font-bold ${stat.color || 'text-white'}`}>{stat.value}</div>
            </div>
          ))}
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="p-4 md:p-6 border-b border-zinc-800 flex items-center gap-2">
            <Users className="w-5 h-5 text-zinc-400" />
            <h2 className="text-xl font-semibold">Users</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-950 text-zinc-400">
                <tr>
                  <th className="px-6 py-3 font-medium">Email</th>
                  <th className="px-6 py-3 font-medium">Role</th>
                  <th className="px-6 py-3 font-medium">Status</th>
                  <th className="px-6 py-3 font-medium">Joined</th>
                  <th className="px-6 py-3 font-medium">Last Login</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-zinc-800/50 transition-colors">
                    <td className="px-6 py-4 font-medium">{u.email}</td>
                    <td className="px-6 py-4">
                      <select
                        value={u.role}
                        onChange={(e) => handleUpdateRole(u.id, e.target.value as 'user' | 'admin')}
                        className="bg-zinc-950 border border-zinc-700 rounded-md px-2 py-1 outline-none focus:border-zinc-500"
                        disabled={u.id === user?.id}
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="px-6 py-4">
                      <select
                        value={u.access_status}
                        onChange={(e) => handleUpdateStatus(u.id, e.target.value as 'active' | 'suspended' | 'pending')}
                        className="bg-zinc-950 border border-zinc-700 rounded-md px-2 py-1 outline-none focus:border-zinc-500"
                        disabled={u.id === user?.id}
                      >
                        <option value="active">Active</option>
                        <option value="pending">Pending</option>
                        <option value="suspended">Suspended</option>
                      </select>
                    </td>
                    <td className="px-6 py-4 text-zinc-400">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="px-6 py-4 text-zinc-400">{u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="p-4 md:p-6 border-b border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Key className="w-5 h-5 text-zinc-400" />
              <h2 className="text-xl font-semibold">Invite Codes</h2>
            </div>
            <form onSubmit={handleGenerateCode} className="flex items-center gap-2">
              <input
                type="number"
                placeholder="Max uses (optional)"
                value={newCodeMaxUses}
                onChange={(e) => setNewCodeMaxUses(e.target.value)}
                className="bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-zinc-500 w-36"
                min="1"
              />
              <button
                type="submit"
                className="bg-white text-black px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-zinc-200 transition-colors flex items-center gap-1.5"
              >
                <Plus className="w-4 h-4" /> Generate
              </button>
            </form>
          </div>
          
          {justGeneratedCode && (
            <div className="p-4 bg-green-500/10 border-b border-green-500/20 flex flex-col md:flex-row items-center justify-between gap-4">
              <div>
                <p className="text-green-400 font-medium mb-1">New Invite Code Generated!</p>
                <p className="text-sm text-zinc-400">Save this code now. It will not be shown again.</p>
              </div>
              <div className="flex items-center gap-2 bg-zinc-950 p-2 rounded-lg border border-zinc-800">
                <code className="text-lg font-mono px-2">{justGeneratedCode}</code>
                <button
                  onClick={() => copyToClipboard(justGeneratedCode)}
                  className="p-2 hover:bg-zinc-800 rounded-md transition-colors"
                  title="Copy code"
                >
                  {copiedCode === justGeneratedCode ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4 text-zinc-400" />}
                </button>
              </div>
            </div>
          )}

          <div className="overflow-x-auto p-4 md:p-6">
            <table className="w-full text-left text-sm">
              <thead className="text-zinc-400">
                <tr>
                  <th className="pb-3 font-medium">Code ID (Redacted)</th>
                  <th className="pb-3 font-medium">Uses</th>
                  <th className="pb-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {inviteCodes.map((code) => (
                  <tr key={code.id}>
                    <td className="py-3 font-mono text-zinc-500">{code.id}</td>
                    <td className="py-3">
                      <span className="bg-zinc-800 px-2 py-1 rounded text-xs">
                        {code.used_count} / {code.max_uses === null ? '∞' : code.max_uses}
                      </span>
                    </td>
                    <td className="py-3 text-zinc-400">{new Date(code.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {inviteCodes.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-8 text-center text-zinc-500 italic">No invite codes generated yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
