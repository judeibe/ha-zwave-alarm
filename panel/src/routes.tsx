import { createBrowserRouter, createMemoryRouter, Navigate, type RouteObject } from "react-router";
import type { Api } from "./api";
import { Layout, LoadError } from "./Layout";
import { PeoplePage } from "./pages/PeoplePage";
import { SensorsPage } from "./pages/SensorsPage";
import { ZonesPage } from "./pages/ZonesPage";

export function createRoutes(api: Api): RouteObject[] {
  return [
    {
      id: "root",
      path: "/",
      Component: Layout,
      ErrorBoundary: LoadError,
      loader: () => api.overview(),
      HydrateFallback: () => <p className="za-muted">Loading…</p>,
      children: [
        { index: true, element: <Navigate to="sensors" replace /> },
        { path: "sensors", Component: SensorsPage },
        { path: "zones", Component: ZonesPage },
        { path: "people", Component: PeoplePage },
        { path: "*", element: <Navigate to="/sensors" replace /> },
      ],
    },
  ];
}

/** Deep links (/<prefix>/zones) survive a reload: HA's frontend serves its index for any path under a panel. */
export const createPanelRouter = (api: Api, basename: string) => createBrowserRouter(createRoutes(api), { basename });
export const createTestRouter = (api: Api, path = "/") =>
  createMemoryRouter(createRoutes(api), { initialEntries: [path] });
