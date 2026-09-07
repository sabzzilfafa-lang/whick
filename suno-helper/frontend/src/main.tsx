import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./i18n";
import "./index.css";
import { startHeartbeat } from "./heartbeat";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);

// 브라우저 탭이 닫히면 하트비트가 멈추고, 백엔드가 이를 감지해 자동 종료한다.
startHeartbeat();
