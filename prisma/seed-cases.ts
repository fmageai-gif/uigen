/**
 * Seeds the Case table from the HP_ADHOC_ Derp* view.
 *
 * Idempotent: re-running upserts the case metadata but never clears
 * `openedAt`, so an already-opened case stays opened.
 *
 * Run with: npx tsx prisma/seed-cases.ts
 */
import { PrismaClient } from "../src/generated/prisma";

const prisma = new PrismaClient();

interface SeedCase {
  caseId: string;
  subject: string;
  createdOn: string;
  modifiedBy: string | null;
  resolution: string | null;
  quickCase: boolean;
  /** Pre-opened before the app existed — recorded in case-log/opened-cases.md */
  openedAt?: string;
}

// Subjects marked with "…" are truncated in the Dynamics grid and can be
// backfilled once the full view is exported.
const CASES: SeedCase[] = [
  { caseId: "5163090341", subject: "Printer not eligible for Insta…", createdOn: "2026-08-06T01:13:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true, openedAt: "2026-08-06T02:00:00Z" },
  { caseId: "5163090187", subject: "AIP - Misroute", createdOn: "2026-08-06T01:09:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163088476", subject: "Troubleshooting Printing Is…", createdOn: "2026-08-06T00:27:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163085740", subject: "Printer issue", createdOn: "2026-08-05T23:29:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163084695", subject: "ii- offline", createdOn: "2026-08-05T23:08:00Z", modifiedBy: "Jayson Cerace", resolution: "Remote Solution", quickCase: false },
  { caseId: "5163084403", subject: "AIP Printer issue", createdOn: "2026-08-05T23:01:00Z", modifiedBy: "Jayson Cerace", resolution: null, quickCase: true },
  { caseId: "5163084243", subject: "Troubleshooting Printing Is…", createdOn: "2026-08-05T22:58:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163083811", subject: "HW UNABLE TO PRINT", createdOn: "2026-08-05T22:49:00Z", modifiedBy: "Jinky Malate", resolution: "Remote Solution", quickCase: false },
  { caseId: "5163082775", subject: "Troubleshooting Printing Is…", createdOn: "2026-08-05T22:28:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163082705", subject: "AIP issue", createdOn: "2026-08-05T22:27:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163082135", subject: "Troubleshooting Printing Is…", createdOn: "2026-08-05T22:15:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163081581", subject: "ii billing update", createdOn: "2026-08-05T22:03:00Z", modifiedBy: "Irene Juson", resolution: "Case Voided", quickCase: false },
  { caseId: "5163080451", subject: "Laptop issue/offline", createdOn: "2026-08-05T21:41:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163078937", subject: "II - cancel instant ink subscr…", createdOn: "2026-08-05T21:05:00Z", modifiedBy: "Percival Magante", resolution: "Subscription c…", quickCase: false },
  { caseId: "5163077290", subject: "ghost call", createdOn: "2026-08-05T20:24:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
  { caseId: "5163047938", subject: "no info", createdOn: "2026-08-05T09:24:00Z", modifiedBy: "SYSTEM", resolution: null, quickCase: true },
];

async function main() {
  for (const c of CASES) {
    await prisma.case.upsert({
      where: { caseId: c.caseId },
      // Metadata refreshes on re-seed; openedAt is deliberately absent so a
      // claimed case is never released.
      update: {
        subject: c.subject,
        createdOn: new Date(c.createdOn),
        modifiedBy: c.modifiedBy,
        resolution: c.resolution,
        quickCase: c.quickCase,
      },
      create: {
        caseId: c.caseId,
        subject: c.subject,
        createdOn: new Date(c.createdOn),
        modifiedBy: c.modifiedBy,
        resolution: c.resolution,
        quickCase: c.quickCase,
        openedAt: c.openedAt ? new Date(c.openedAt) : null,
      },
    });
  }

  const total = await prisma.case.count();
  const opened = await prisma.case.count({ where: { NOT: { openedAt: null } } });
  console.log(`Seeded ${CASES.length} cases. Table now holds ${total} (${opened} opened).`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
