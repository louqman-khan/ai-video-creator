import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

/** Local mode only: points a new user to the Setup page until the keys and speech model are in place. Silent when the server has no setup (hosted) or is unreachable. */
export function SetupBanner() {
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let live = true;
    api.setupStatus().then(
      (s) => live && setMissing(!s.keys.gemini_api_key || !s.models.whisper),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  if (!missing) return null;
  return (
    <p className="alert" role="status">
      This computer still needs its own free keys and the speech model before the first video. <Link to="/setup">Open Settings</Link>
    </p>
  );
}
