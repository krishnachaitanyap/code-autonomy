import type { Metadata } from 'next';
import './globals.css';
import Navbar from '@/components/Navbar';
import Tour from '@/components/Tour';
import { TourProvider } from '@/components/TourProvider';

export const metadata: Metadata = {
  title: 'Code Autonomy',
  description: 'AI-powered code generation and analysis dashboard',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TourProvider>
          <Navbar />
          <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {children}
          </main>
          <Tour />
        </TourProvider>
      </body>
    </html>
  );
}
