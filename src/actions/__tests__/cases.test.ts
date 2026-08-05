import { test, expect, vi, beforeEach } from "vitest";

const findUnique = vi.fn();
const updateMany = vi.fn();
const findFirst = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    case: {
      findUnique: (...args: unknown[]) => findUnique(...args),
      updateMany: (...args: unknown[]) => updateMany(...args),
      findFirst: (...args: unknown[]) => findFirst(...args),
    },
  },
}));

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const { openCase, nextCase } = await import("../cases");

const unopened = {
  id: "c1",
  caseId: "5163090187",
  subject: "AIP - Misroute",
  createdOn: new Date("2026-08-06T01:09:00Z"),
  modifiedBy: "SYSTEM",
  resolution: null,
  quickCase: true,
  openedAt: null,
  openedBy: null,
};

beforeEach(() => {
  findUnique.mockReset();
  updateMany.mockReset();
  findFirst.mockReset();
});

test("opens an unopened case and stamps openedAt", async () => {
  const opened = { ...unopened, openedAt: new Date("2026-08-06T03:00:00Z") };
  findUnique.mockResolvedValueOnce(unopened).mockResolvedValueOnce(opened);
  updateMany.mockResolvedValue({ count: 1 });

  const result = await openCase("5163090187");

  expect(result.success).toBe(true);
  expect(result.case?.openedAt).toEqual(opened.openedAt);
});

test("refuses to open the same case ID twice", async () => {
  findUnique.mockResolvedValue({
    ...unopened,
    openedAt: new Date("2026-08-06T03:00:00Z"),
  });

  const result = await openCase("5163090187");

  expect(result.success).toBe(false);
  expect(result.error).toContain("already opened");
  expect(updateMany).not.toHaveBeenCalled();
});

test("guards the claim on openedAt being null", async () => {
  findUnique.mockResolvedValue(unopened);
  updateMany.mockResolvedValue({ count: 1 });

  await openCase("5163090187");

  expect(updateMany).toHaveBeenCalledWith({
    where: { caseId: "5163090187", openedAt: null },
    data: expect.objectContaining({ openedAt: expect.any(Date) }),
  });
});

test("loses the race gracefully when another caller claims first", async () => {
  findUnique.mockResolvedValue(unopened);
  updateMany.mockResolvedValue({ count: 0 });

  const result = await openCase("5163090187");

  expect(result.success).toBe(false);
  expect(result.error).toContain("already opened");
});

test("rejects a case ID that is not in the list", async () => {
  findUnique.mockResolvedValue(null);

  const result = await openCase("9999999999");

  expect(result.success).toBe(false);
  expect(result.error).toContain("not in the list");
});

test("rejects an empty case ID", async () => {
  const result = await openCase("   ");

  expect(result.success).toBe(false);
  expect(result.error).toBe("Case ID is required");
  expect(findUnique).not.toHaveBeenCalled();
});

test("trims surrounding whitespace before lookup", async () => {
  findUnique.mockResolvedValue(unopened);
  updateMany.mockResolvedValue({ count: 1 });

  await openCase("  5163090187  ");

  expect(findUnique).toHaveBeenCalledWith({ where: { caseId: "5163090187" } });
});

test("nextCase returns the newest unopened case", async () => {
  findFirst.mockResolvedValue(unopened);

  const result = await nextCase();

  expect(result).toEqual(unopened);
  expect(findFirst).toHaveBeenCalledWith({
    where: { openedAt: null },
    orderBy: { createdOn: "desc" },
  });
});

test("nextCase returns null once the pool is exhausted", async () => {
  findFirst.mockResolvedValue(null);

  expect(await nextCase()).toBeNull();
});
