import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { AppStateProvider } from "./state/AppState";
import PortfolioOverview from "./pages/PortfolioOverview";
import SleeveLayout from "./pages/SleeveLayout";
import SleeveOverview from "./pages/SleeveOverview";
import SleeveStocks from "./pages/SleeveStocks";
import Performance from "./pages/Performance";
import Holdings from "./pages/Holdings";
import Heatmaps from "./pages/Heatmaps";
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
              <Route index element={<PortfolioOverview />} />
              <Route path="performance" element={<Performance />} />
              <Route path="holdings" element={<Holdings />} />
              <Route path="heatmap" element={<Heatmaps />} />
              <Route path="risk" element={<Risk />} />
              <Route path="transactions" element={<Transactions />} />
              <Route path="history" element={<History />} />
              <Route path="sleeves/:sleeve" element={<SleeveLayout />}>
                <Route index element={<SleeveOverview />} />
                <Route path="stocks" element={<SleeveStocks />} />
                <Route path="performance" element={<Performance />} />
                <Route path="risk" element={<Risk />} />
                <Route path="history" element={<History />} />
                <Route path="transactions" element={<Transactions />} />
              </Route>
              <Route path="data-quality" element={<DataQuality />} />
              <Route path="methodology" element={<Methodology />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AppStateProvider>
    </QueryClientProvider>
  );
}
