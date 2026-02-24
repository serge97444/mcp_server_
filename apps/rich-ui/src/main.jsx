import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// same logic as in readhost but happens once at start
const host = window.openai || {};
const toolOutput = host.toolOutput;
const data =
  (toolOutput && typeof toolOutput === "object" && "data" in toolOutput
    ? toolOutput.data
    : toolOutput) ||
  host.structuredContent ||
  host.widgetState ||
  window.__APP_DATA__ ||
  {};
// function allowing to read the parameters of a request
console.log("window location " , window.location.search);
const params = new URLSearchParams(window.location.search);
const debug =
  params.get("debug") === "1" ||
  window.__WIDGET_DEBUG__ === true ||
  window.__WIDGET_DEBUG__ === "true";

const root = createRoot(document.getElementById("root"));
root.render(<App data={data} debug={debug} host={host} />);
