import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createApi } from "@/lib/webApi";
import { createAppRouter, createQueryClient } from "./router";
import "./index.css";

const api = await createApi();
const queryClient = createQueryClient();
const router = createAppRouter({ api, queryClient });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
