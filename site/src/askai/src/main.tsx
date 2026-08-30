import { createRoot } from "react-dom/client";
import App from "./App";

const container = document.getElementById("askai-root");
if (container) {
  createRoot(container).render(<App />);
}
