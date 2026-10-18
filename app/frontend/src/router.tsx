// Routes (TanStack Router, code-based): overview, drawing (source), CAD run, and settings.
// Loaders fill the query cache; an unknown ID becomes the not-found page instead of a broken view.
import { QueryClient, useQuery } from "@tanstack/react-query";
import {
  createRootRouteWithContext, createRoute, createRouter, notFound, Outlet, redirect, useRouter, type ErrorComponentProps,
} from "@tanstack/react-router";
import { ErrorState } from "@/components/ErrorState";
import { Sidebar } from "@/components/Sidebar";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Toaster } from "@/components/ui/sonner";
import { useApi, type RouterContext } from "@/lib/apiContext";
import { useEffect } from "react";
import { errorCode } from "@/lib/errors";
import { analysisQuery, capabilitiesQuery, runQuery, sourceQuery } from "@/lib/queries";
import { isSettingsSection } from "@/lib/settings";
import { UploadProvider } from "@/lib/uploads";
import { OverviewPage } from "@/pages/OverviewPage";
import { RUN_TABS, RunPage, type RunTab } from "@/pages/RunPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SourcePage, type Step } from "@/pages/SourcePage";

/** A file dropped outside a drop zone must not open in the browser: that would leave the app and lose its state. */
function useDropGuard() {
  useEffect(() => {
    const block = (evt: DragEvent) => { if (evt.dataTransfer?.types.includes("Files")) evt.preventDefault(); };
    window.addEventListener("dragover", block);
    window.addEventListener("drop", block);
    return () => { window.removeEventListener("dragover", block); window.removeEventListener("drop", block); };
  }, []);
}

function Shell() {
  const api = useApi();
  const { data: caps } = useQuery(capabilitiesQuery(api));
  useDropGuard();
  return (
    <UploadProvider>
      <div className="grid h-full grid-cols-[232px_minmax(0,1fr)] max-[1000px]:h-auto max-[1000px]:min-h-full max-[1000px]:grid-cols-1">
        <Sidebar />
        <main className="flex min-h-0 min-w-0 flex-col gap-3 border-l bg-surface px-6 py-5 max-[1000px]:border-t max-[1000px]:border-l-0 max-[1000px]:p-4">
          {caps?.simulated && (
            <Alert className="border-warn-line bg-warn-bg py-2">
              <AlertTitle>Simulierter Dienst</AlertTitle>
              <AlertDescription>
                Läufe, Parameter und Ergebnisse stammen aus synthetischen Fixtures. Sie sind kein CAD-Ergebnis und kein Abnahmenachweis.
              </AlertDescription>
            </Alert>
          )}
          <Outlet />
        </main>
      </div>
      <Toaster position="bottom-right" />
    </UploadProvider>
  );
}

function RouteError({ error }: ErrorComponentProps) {
  const router = useRouter();
  return <ErrorState title="Ansicht nicht verfügbar" error={error} onRetry={() => void router.invalidate()} />;
}

/** Map NOT_FOUND from the service to the not-found page. Other errors go to the route error view. */
async function load(task: Promise<unknown>) {
  try { await task; } catch (err) {
    if (errorCode(err) === "NOT_FOUND") throw notFound();
    throw err;
  }
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Shell,
  notFoundComponent: () => <ErrorState title="Nicht gefunden" />,
  errorComponent: RouteError,
});

const overviewRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: OverviewPage });

const sourceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sources/$sourceId",
  // Optional search parameters: links without them open step 1 or the parameter tab.
  validateSearch: (search: Record<string, unknown>): { step?: Step } => {
    const step = Number(search.step);
    return step >= 2 && step <= 4 ? { step: step as Step } : {};
  },
  loader: ({ context: { api, queryClient }, params: { sourceId } }) => load(Promise.all([
    queryClient.ensureQueryData(sourceQuery(api, sourceId)),
    queryClient.ensureQueryData(analysisQuery(api, sourceId)),
  ])),
  component: SourcePage,
});

const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId",
  validateSearch: (search: Record<string, unknown>): { tab?: RunTab } =>
    RUN_TABS.includes(search.tab as RunTab) && search.tab !== "parameter" ? { tab: search.tab as RunTab } : {},
  loader: ({ context: { api, queryClient }, params: { runId } }) => load(queryClient.ensureQueryData(runQuery(api, runId))),
  component: RunPage,
});

const settingsIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  beforeLoad: () => { throw redirect({ to: "/settings/$section", params: { section: "agent" } }); },
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings/$section",
  loader: ({ params: { section } }) => { if (!isSettingsSection(section)) throw notFound(); },
  component: SettingsPage,
});

export function createAppRouter(context: RouterContext) {
  return createRouter({
    routeTree: rootRoute.addChildren([overviewRoute, sourceRoute, runRoute, settingsIndexRoute, settingsRoute]),
    context,
    defaultPreload: "intent",
    // The query cache owns freshness; the router must not cache loader results separately.
    defaultPreloadStaleTime: 0,
  });
}

declare module "@tanstack/react-router" {
  interface Register { router: ReturnType<typeof createAppRouter> }
}

export const createQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: {
      // A missing ID does not appear on retry; other failures get one retry.
      retry: (count, err) => errorCode(err) !== "NOT_FOUND" && errorCode(err) !== "CAPABILITY_UNAVAILABLE" && count < 1,
      refetchOnWindowFocus: false,
    },
  },
});
