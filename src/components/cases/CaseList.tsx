"use client";

import { useState, useTransition } from "react";
import { CheckCircle2, Lock, Search, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { openCase, type CaseRecord } from "@/actions/cases";
import { cn } from "@/lib/utils";

interface CaseListProps {
  cases: CaseRecord[];
}

function formatDate(value: Date | string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function CaseList({ cases }: CaseListProps) {
  const [rows, setRows] = useState<CaseRecord[]>(cases);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const openedCount = rows.filter((r) => r.openedAt).length;
  const remaining = rows.length - openedCount;

  function handleOpen(caseId: string) {
    setPendingId(caseId);
    setMessage(null);

    startTransition(async () => {
      const result = await openCase(caseId);

      if (result.success && result.case) {
        const opened = result.case;
        setRows((prev) =>
          prev.map((r) => (r.caseId === opened.caseId ? opened : r))
        );
        setMessage({ type: "ok", text: `Opened case ${opened.caseId} — ${opened.subject}` });
      } else {
        setMessage({ type: "err", text: result.error ?? "Could not open case" });
      }

      setPendingId(null);
    });
  }

  const visible = rows.filter((r) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      r.caseId.toLowerCase().includes(q) || r.subject.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by case ID or subject"
            className="pl-9"
          />
        </div>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span>
            <span className="font-semibold text-foreground">{remaining}</span> available
          </span>
          <span>
            <span className="font-semibold text-foreground">{openedCount}</span> opened
          </span>
        </div>
      </div>

      {message && (
        <div
          role="status"
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-2 text-sm",
            message.type === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-amber-200 bg-amber-50 text-amber-900"
          )}
        >
          {message.type === "ok" ? (
            <CheckCircle2 className="size-4 shrink-0" />
          ) : (
            <AlertCircle className="size-4 shrink-0" />
          )}
          {message.text}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left">
            <tr>
              <th className="px-4 py-2.5 font-medium">Case ID</th>
              <th className="px-4 py-2.5 font-medium">Subject</th>
              <th className="px-4 py-2.5 font-medium">Created On</th>
              <th className="px-4 py-2.5 font-medium">Modified By</th>
              <th className="px-4 py-2.5 font-medium">Resolution</th>
              <th className="px-4 py-2.5 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((c) => {
              const isOpened = Boolean(c.openedAt);
              return (
                <tr
                  key={c.caseId}
                  className={cn(
                    "border-t",
                    isOpened && "bg-muted/30 text-muted-foreground"
                  )}
                >
                  <td className="px-4 py-2.5 font-mono">{c.caseId}</td>
                  <td className="px-4 py-2.5">{c.subject}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap">{formatDate(c.createdOn)}</td>
                  <td className="px-4 py-2.5">{c.modifiedBy ?? "—"}</td>
                  <td className="px-4 py-2.5">{c.resolution ?? "—"}</td>
                  <td className="px-4 py-2.5 text-right">
                    {isOpened ? (
                      <span
                        className="inline-flex items-center gap-1.5 text-xs"
                        title={`Opened ${formatDate(c.openedAt)}`}
                      >
                        <Lock className="size-3.5" />
                        Opened {formatDate(c.openedAt)}
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => handleOpen(c.caseId)}
                        disabled={pendingId === c.caseId}
                      >
                        {pendingId === c.caseId ? "Opening…" : "Open"}
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr className="border-t">
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  No cases match “{query}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
