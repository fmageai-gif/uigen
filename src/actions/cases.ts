"use server";

import { prisma } from "@/lib/prisma";
import { revalidatePath } from "next/cache";

export interface CaseRecord {
  id: string;
  caseId: string;
  subject: string;
  createdOn: Date;
  modifiedBy: string | null;
  resolution: string | null;
  quickCase: boolean;
  openedAt: Date | null;
  openedBy: string | null;
}

export interface OpenCaseResult {
  success: boolean;
  error?: string;
  case?: CaseRecord;
}

export async function listCases(): Promise<CaseRecord[]> {
  return prisma.case.findMany({
    orderBy: { createdOn: "desc" },
  });
}

/**
 * Claims a case for work. A case ID can only ever be opened once — the
 * guard is the `openedAt: null` filter inside the update itself, so two
 * concurrent callers cannot both win the row.
 */
export async function openCase(
  caseId: string,
  openedBy?: string
): Promise<OpenCaseResult> {
  const trimmed = caseId?.trim();

  if (!trimmed) {
    return { success: false, error: "Case ID is required" };
  }

  try {
    const existing = await prisma.case.findUnique({
      where: { caseId: trimmed },
    });

    if (!existing) {
      return { success: false, error: `Case ${trimmed} is not in the list` };
    }

    if (existing.openedAt) {
      return {
        success: false,
        error: `Case ${trimmed} was already opened on ${existing.openedAt.toLocaleString()}`,
        case: existing,
      };
    }

    const claimed = await prisma.case.updateMany({
      where: { caseId: trimmed, openedAt: null },
      data: { openedAt: new Date(), openedBy: openedBy ?? null },
    });

    if (claimed.count === 0) {
      return {
        success: false,
        error: `Case ${trimmed} was already opened`,
      };
    }

    const updated = await prisma.case.findUnique({
      where: { caseId: trimmed },
    });

    revalidatePath("/cases");
    return { success: true, case: updated ?? undefined };
  } catch (error) {
    console.error("Open case error:", error);
    return { success: false, error: "An error occurred while opening the case" };
  }
}

/** Next unopened case, newest first. Returns null once the pool is exhausted. */
export async function nextCase(): Promise<CaseRecord | null> {
  return prisma.case.findFirst({
    where: { openedAt: null },
    orderBy: { createdOn: "desc" },
  });
}
