'use client';

import { useState } from 'react';
import { Syne, DM_Mono, Inter } from 'next/font/google';
import './globals.css';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import StatusBar from '@/components/layout/StatusBar';

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <html
      lang="en"
      className={`${syne.variable} ${dmMono.variable} ${inter.variable} dark`}
    >
      <body className="min-h-screen">
        {/* App Shell: Sidebar + Main Content */}
        <div className="flex min-h-screen">
          {/* Fixed Sidebar */}
          <Sidebar
            isMobileOpen={sidebarOpen}
            onMobileClose={() => setSidebarOpen(false)}
          />

          {/* Main Content Area
              - Mobile: no left margin (sidebar is a drawer, not always-visible)
              - Desktop collapsed (lg): 64px offset
              - Desktop expanded (xl): 240px offset */}
          <div className="flex flex-col flex-1 ml-0 lg:ml-16 xl:ml-60 relative z-[1]">
            {/* Sticky Header */}
            <Header onMenuOpen={() => setSidebarOpen(true)} />

            {/* Page Content */}
            <main className="flex-1 p-4 lg:p-6">
              {children}
            </main>

            {/* Fixed Bottom Status Bar */}
            <StatusBar />
          </div>
        </div>
      </body>
    </html>
  );
}
