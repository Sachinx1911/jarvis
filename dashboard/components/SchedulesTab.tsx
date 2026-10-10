"use client";

import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import ModuleStatus, { Adapter } from "./ModuleStatus";

export default function SchedulesTab() {
  const { data, error } = usePoll(() => api<Adapter>("/api/schedules"), 10000);
  return (
    <section className="panel">
      <h2>Schedules</h2>
      <p className="small muted">
        Skill and agent schedules (PLAN.md 10.3) come with the proactive module. Unattended runs may only do T0/T1;
        anything else waits in the approval queue.
      </p>
      {error && <div className="error">{error}</div>}
      {data && <ModuleStatus title="Scheduler" a={data} />}
    </section>
  );
}
