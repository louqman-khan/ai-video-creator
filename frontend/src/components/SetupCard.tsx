import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Icon } from "./Icon";

/** Sidebar card (local mode): says whether the keys and models are in place, and links to Setup when something is missing. Silent when the server has no setup. */
export function SetupCard() {
  const [state, setState] = useState<"unknown" | "ready" | "missing">("unknown");
  useEffect(() => {
    let live = true;
    api.setupStatus().then(
      (s) => live && setState(s.keys.gemini_api_key && s.models.whisper ? "ready" : "missing"),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  if (state === "unknown") return null;
  return state === "ready" ? (
    <div className="side-card side-card-ok"><Icon name="check" size={16} /><span><strong>Ready to create</strong><span className="muted">Keys and models are set up.</span></span></div>
  ) : (
    <Link to="/setup" className="side-card side-card-warn"><Icon name="settings" size={16} /><span><strong>Finish setup</strong><span className="muted">Add your free keys and download the models.</span></span></Link>
  );
}
