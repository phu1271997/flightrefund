import { BrowserRouter, Route, Routes } from 'react-router-dom';
import LandingPage from './LandingPage.jsx';
import AppView from './AppView.jsx';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/app" element={<AppView />} />
        <Route path="*" element={<LandingPage />} />
      </Routes>
    </BrowserRouter>
  );
}
