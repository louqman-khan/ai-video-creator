import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../store/auth";

/** Local mode only: points a new user to the Setup page until the keys and speech model are in place. Silent when the server has no setup (hosted) or is unreachable. */
export function SetupBanner() {
  const [missing, setMissing] = useState(false);
  const hosted = useAuth((s) => s.account?.mode === "hosted");
  useEffect(() => {
    if (hosted) return;   // a hosted site has no keys or models for a customer to set up: there is nothing to ask the server
    let live = true;
    api.setupStatus().then(
      (s) => live && setMissing(!s.keys.gemini_api_key || !s.models.whisper),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [hosted]);
  if (!missing) return null;
  return (
    <p className="alert" role="status">
      This computer still needs its own free keys and the speech model before the first video. <Link to="/setup">Open Settings</Link>
    </p>
  );
}
