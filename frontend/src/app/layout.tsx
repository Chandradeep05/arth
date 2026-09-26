'use client';

import { useState } from 'react';
import { Syne, DM_Mono, Inter } from 'next/font/google';
import './globals.css';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import StatusBar from '@/components/layout/StatusBar';
import { AuthProvider, useAuth } from '@/lib/auth/AuthProvider';
import PendingActivation from '@/components/layout/PendingActivation';

const syne = Syne({
  variable: '--font-syne',
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  display: 'swap',
});

const dmMono = DM_Mono({
  variable: '--font-dm-mono',
  subsets: ['latin'],
  weight: ['300', '400', '500'],
  display: 'swap',
});

const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
});

// NOTE: metadata export is removed here because 'use client' layouts cannot
// export metadata. Move metadata to a separate metadata.ts if needed, or
// keep metadata in a server wrapper and make this component a child.
// For now the layout is client-only to support the mobile sidebar state.

// Inner component that can use useAuth (must be inside AuthProvider)
function AppContent({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { user, accessStatus, loading } = useAuth();

  // Gate: if user is authenticated but access is pending, show activation screen
  if (!loading && user && accessStatus === 'pending') {
    return <PendingActivation />;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar
        isMobileOpen={sidebarOpen}
        onMobileClose={() => setSidebarOpen(false)}
      />
      <div className="flex flex-col flex-1 ml-0 lg:ml-16 xl:ml-60 relative z-[1] min-w-0 max-w-full overflow-x-hidden">
        <Header onMenuOpen={() => setSidebarOpen(true)} />
        <main className="flex-1 p-3 sm:p-4 lg:p-5 pb-14 sm:pb-16 min-w-0 max-w-full">
          {children}
        </main>
        <StatusBar />
      </div>
    </div>
  );
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${syne.variable} ${dmMono.variable} ${inter.variable} dark`}
    >
      <body className="min-h-screen">
        <AuthProvider>
          <AppContent>{children}</AppContent>
        </AuthProvider>
      </body>
    </html>
  );
}
