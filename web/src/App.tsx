/**
 * Nexora web frontend
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout/Layout';
import { ToastProvider } from './components/Toast';
import { Home } from './pages/Home';
import { Search } from './pages/Search';
import { Downloads } from './pages/Downloads';
import { Subscriptions } from './pages/Subscriptions';
import { Organize } from './pages/Organize';
import { Files } from './pages/Files';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10000,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Home />} />
              <Route path="/search" element={<Search />} />
              <Route path="/downloads" element={<Downloads />} />
              <Route path="/subscriptions" element={<Subscriptions />} />
              <Route path="/organize" element={<Organize />} />
              <Route path="/files" element={<Files />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
