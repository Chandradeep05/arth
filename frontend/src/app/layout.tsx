import type { Metadata } from "next";
import { Syne, DM_Mono, Inter } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import StatusBar from "@/components/layout/StatusBar";

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  display: "swap",
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ARTH — AI Research & Trading Hub",
  description:
    "Institutional-grade decision-support infrastructure combining real-time market intelligence, AI-generated research, probabilistic forecasting, sentiment analysis, and risk detection.",
  keywords: [
    "AI finance",
    "market intelligence",
    "stock analysis",
    "financial research",
    "NSE",
    "BSE",
  ],
};

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
        {/* App Shell: Sidebar + Main Content */}
        <div className="flex min-h-screen">
          {/* Fixed Sidebar */}
          <Sidebar />

          {/* Main Content Area — offset by sidebar width */}
          <div className="flex flex-col flex-1 ml-16 lg:ml-60 relative z-[1]">
            {/* Sticky Header */}
            <Header />

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
