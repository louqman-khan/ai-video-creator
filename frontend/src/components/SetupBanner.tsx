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
      Finish setting up before your first video: add your free keys and download the speech model. <Link to="/setup">Open Setup</Link>
    </p>
  );
}
