import { listCases } from "@/actions/cases";
import { CaseList } from "@/components/cases/CaseList";

export const dynamic = "force-dynamic";

export default async function CasesPage() {
  const cases = await listCases();

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Case Queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          HP_ADHOC_ Derp* view. Opening a case claims it — a case ID can only be
          opened once.
        </p>
      </header>

      <CaseList cases={cases} />
    </main>
  );
}
