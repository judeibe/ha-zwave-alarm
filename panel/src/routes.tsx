import { createBrowserRouter, createMemoryRouter, Navigate, type RouteObject } from "react-router";
import type { Api } from "./api";
import { LoadError, LoadingState, Shell } from "./Shell";
import { OverviewPage } from "./pages/OverviewPage";
import { KeypadsPage } from "./pages/KeypadsPage";
import { PeoplePage, PersonSheet } from "./pages/PeoplePage";
import { AddSensorSheet, SensorSheet, SensorsPage } from "./pages/SensorsPage";
import { NewZoneSheet, ZoneSheet, ZonesPage } from "./pages/ZonesPage";

export function createRoutes(api: Api): RouteObject[] {
  return [
    {
      id: "root",
      path: "/",
      Component: Shell,
      ErrorBoundary: LoadError,
      loader: () => api.overview(),
      HydrateFallback: LoadingState,
      children: [
        { index: true, element: <Navigate to="overview" replace /> },
        { path: "overview", Component: OverviewPage },
        {
          path: "sensors",
          Component: SensorsPage,
          children: [
            { path: "add/:nodeId", Component: AddSensorSheet },
            { path: ":sensorId", Component: SensorSheet },
          ],
        },
        {
          path: "zones",
          Component: ZonesPage,
          children: [
            { path: "new", Component: NewZoneSheet },
            { path: ":zoneId", Component: ZoneSheet },
          ],
        },
        { path: "people", Component: PeoplePage, children: [{ path: ":personId", Component: PersonSheet }] },
        { path: "keypads", Component: KeypadsPage },
        { path: "*", element: <Navigate to="/overview" replace /> },
      ],
    },
  ];
}

/** Deep links (/<prefix>/zones) survive a reload: HA's frontend serves its index for any path under a panel. */
export const createPanelRouter = (api: Api, basename: string) => createBrowserRouter(createRoutes(api), { basename });
export const createTestRouter = (api: Api, path = "/") =>
  createMemoryRouter(createRoutes(api), { initialEntries: [path] });
