import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { AppStateProvider } from "./state/AppState";
import Overview from "./pages/Overview";
import Performance from "./pages/Performance";
import Holdings from "./pages/Holdings";
import Heatmap from "./pages/Heatmap";
import Risk from "./pages/Risk";
import Transactions from "./pages/Transactions";
import History from "./pages/History";
import DataQuality from "./pages/DataQuality";
import Methodology from "./pages/Methodology";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppStateProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="performance" element={<Performance />} />
              <Route path="holdings" element={<Holdings />} />
              <Route path="heatmap" element={<Heatmap />} />
              <Route path="risk" element={<Risk />} />
              <Route path="transactions" element={<Transactions />} />
              <Route path="history" element={<History />} />
              <Route path="data-quality" element={<DataQuality />} />
              <Route path="methodology" element={<Methodology />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AppStateProvider>
    </QueryClientProvider>
  );
}
