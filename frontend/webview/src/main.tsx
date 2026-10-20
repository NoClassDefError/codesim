import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './styles.css';
import { App } from './App';
import { SignalsApp } from './SignalsApp';

const isSignalsView =
  document.body.dataset.view === 'signals' ||
  new URLSearchParams(window.location.search).get('view') === 'signals';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ReactFlowProvider>
      {isSignalsView ? <SignalsApp /> : <App />}
    </ReactFlowProvider>
  </StrictMode>,
);
