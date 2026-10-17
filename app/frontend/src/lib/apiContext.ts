// Router context: the selected service adapter and the query client. Routes and components read it here.
import type { QueryClient } from "@tanstack/react-query";
import { useRouteContext } from "@tanstack/react-router";
import type { WebApi } from "./webApi";

export interface RouterContext {
  api: WebApi;
  queryClient: QueryClient;
}

export const useApi = (): WebApi => useRouteContext({ from: "__root__" }).api;
