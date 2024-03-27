import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { FirebaseProvider } from "./context/Firebase";
import "./index.css";
import App from "./App.jsx";
import { SpeedInsights } from "@vercel/speed-insights/react";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <FirebaseProvider>
        <App />
        <SpeedInsights />
      </FirebaseProvider>
    </BrowserRouter>
  </React.StrictMode>
);
