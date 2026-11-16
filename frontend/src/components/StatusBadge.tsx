import type { ProjectStatus } from "../api/types";

const LABEL: Record<ProjectStatus, string> = {
  queued: "Queued",
  running: "Working",
  done: "Ready",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return <span className={`badge badge-${status}`}>{LABEL[status]}</span>;
}
