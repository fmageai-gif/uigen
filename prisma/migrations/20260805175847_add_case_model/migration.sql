-- CreateTable
CREATE TABLE "Case" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "caseId" TEXT NOT NULL,
    "subject" TEXT NOT NULL,
    "createdOn" DATETIME NOT NULL,
    "modifiedBy" TEXT,
    "resolution" TEXT,
    "quickCase" BOOLEAN NOT NULL DEFAULT false,
    "openedAt" DATETIME,
    "openedBy" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateIndex
CREATE UNIQUE INDEX "Case_caseId_key" ON "Case"("caseId");

-- CreateIndex
CREATE INDEX "Case_openedAt_idx" ON "Case"("openedAt");
