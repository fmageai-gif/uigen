import { test, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const openCase = vi.fn();
vi.mock("@/actions/cases", () => ({ openCase: (id: string) => openCase(id) }));

const { CaseList } = await import("../CaseList");

const base = {
  subject: "AIP - Misroute",
  createdOn: new Date("2026-08-06T01:09:00Z"),
  modifiedBy: "SYSTEM",
  resolution: null,
  quickCase: true,
  openedBy: null,
};

const cases = [
  { ...base, id: "c1", caseId: "5163090187", openedAt: null },
  {
    ...base,
    id: "c2",
    caseId: "5163090341",
    subject: "Printer not eligible",
    openedAt: new Date("2026-08-06T02:00:00Z"),
  },
];

afterEach(() => {
  cleanup();
  openCase.mockReset();
});

test("shows an Open button only for unopened cases", () => {
  render(<CaseList cases={cases} />);

  expect(screen.getAllByRole("button", { name: "Open" })).toHaveLength(1);
  expect(screen.getByText(/Opened/)).toBeDefined();
});

test("counts available and opened cases", () => {
  render(<CaseList cases={cases} />);

  const summary = (text: string) =>
    screen.getByText((_, el) => el?.textContent?.trim() === text && el.tagName === "SPAN");

  expect(summary("1 available")).toBeDefined();
  expect(summary("1 opened")).toBeDefined();
});

test("locks the row after a successful open", async () => {
  openCase.mockResolvedValue({
    success: true,
    case: { ...cases[0], openedAt: new Date("2026-08-06T04:00:00Z") },
  });

  render(<CaseList cases={cases} />);
  await userEvent.click(screen.getByRole("button", { name: "Open" }));

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();
  });
  expect(screen.getByRole("status").textContent).toContain("Opened case 5163090187");
});

test("surfaces the error when a case is already opened", async () => {
  openCase.mockResolvedValue({
    success: false,
    error: "Case 5163090187 was already opened",
  });

  render(<CaseList cases={cases} />);
  await userEvent.click(screen.getByRole("button", { name: "Open" }));

  await waitFor(() => {
    expect(screen.getByRole("status").textContent).toContain("already opened");
  });
  expect(screen.getByRole("button", { name: "Open" })).toBeDefined();
});

test("filters by case ID", async () => {
  render(<CaseList cases={cases} />);

  await userEvent.type(
    screen.getByPlaceholderText("Filter by case ID or subject"),
    "5163090341"
  );

  expect(screen.queryByText("5163090187")).toBeNull();
  expect(screen.getByText("5163090341")).toBeDefined();
});

test("filters by subject", async () => {
  render(<CaseList cases={cases} />);

  await userEvent.type(
    screen.getByPlaceholderText("Filter by case ID or subject"),
    "misroute"
  );

  expect(screen.getByText("5163090187")).toBeDefined();
  expect(screen.queryByText("5163090341")).toBeNull();
});
