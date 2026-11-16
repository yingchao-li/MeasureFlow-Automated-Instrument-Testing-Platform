import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { PageBody, PageToolbar } from '@/components/layout/PageToolbar';
import { EmptyState } from '@/components/ui';
import { HealthProvider } from '@/context/HealthContext';
import { ThemeProvider } from '@/context/ThemeContext';
import { ToastProvider } from '@/context/ToastContext';
import { InstrumentsPage } from '@/features/instruments/InstrumentsPage';
import { OverviewPage } from '@/features/overview/OverviewPage';
import { ReportsPage } from '@/features/reports/ReportsPage';
import { SequencesPage } from '@/features/sequences/SequencesPage';
import { Compass } from 'lucide-react';

function NotFound() {
  return (
    <>
      <PageToolbar title="Page not found" />
      <PageBody>
        <EmptyState
          icon={Compass}
          title="This page does not exist"
          description="Use the sidebar to navigate, or go back to the overview."
          action={
            <Link to="/" className="text-sm font-medium text-primary-text underline-offset-2 hover:underline">
              Back to Overview
            </Link>
          }
        />
      </PageBody>
    </>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="instruments" element={<InstrumentsPage />} />
        <Route path="sequences" element={<SequencesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <HealthProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </HealthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
