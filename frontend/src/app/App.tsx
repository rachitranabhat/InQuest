import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as RTooltip from "@radix-ui/react-tooltip";
import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AppShell } from "../components/layout/AppShell";
import { LoadingBlock } from "../components/ui/Primitives";
import { ToastProvider } from "../components/ui/Toast";
import { QueuePage } from "../features/queue/QueuePage";
import { WorkspacePage } from "../features/workspace/WorkspacePage";
import { NotFound } from "../pages/NotFound";
import { ApiError } from "../lib/api";
import { AppProvider } from "./AppContext";
import { ThemeProvider } from "./theme";

const ExplorerPage = lazy(() => import("../features/graph/ExplorerPage"));
const ReportsPage = lazy(() => import("../features/reports/ReportsPage"));
const ScenarioLabPage = lazy(() => import("../features/scenarios/ScenarioLabPage"));
const AnalyticsPage = lazy(() => import("../features/analytics/AnalyticsPage"));
const ComparePage = lazy(() => import("../features/compare/ComparePage"));
const RestrictedRecordsPage = lazy(() => import("../features/restricted/RestrictedRecordsPage"));
const DataMethodologyPage = lazy(() => import("../features/methodology/DataMethodologyPage"));
const DataManagementPage = lazy(() => import("../features/admin/DataManagementPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});

const lazyPage = (el: ReactNode) => <Suspense fallback={<LoadingBlock label="Loading page" />}>{el}</Suspense>;

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <QueuePage /> },
      { path: "cases/:caseId", element: <WorkspacePage /> },
      { path: "cases/:caseId/graph", element: lazyPage(<ExplorerPage />) },
      { path: "compare", element: lazyPage(<ComparePage />) },
      { path: "reports", element: lazyPage(<ReportsPage />) },
      { path: "scenarios", element: lazyPage(<ScenarioLabPage />) },
      { path: "analytics", element: lazyPage(<AnalyticsPage />) },
      { path: "restricted", element: lazyPage(<RestrictedRecordsPage />) },
      { path: "data", element: lazyPage(<DataManagementPage />) },
      { path: "methodology", element: lazyPage(<DataMethodologyPage />) },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App() {
  return (
    <ThemeProvider>
    <QueryClientProvider client={queryClient}>
      <RTooltip.Provider>
        <ToastProvider>
          <AppProvider>
            <RouterProvider router={router} />
          </AppProvider>
        </ToastProvider>
      </RTooltip.Provider>
    </QueryClientProvider>
    </ThemeProvider>
  );
}
