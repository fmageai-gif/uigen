# EQMS — Automatic Invalid-Audit Emails with Power Automate

This makes the formatted TL/OM email send **automatically** whenever an audit
is marked **Invalid** — no clicking, no mailto, no Excel length limits. The
email is built and sent in the Microsoft 365 cloud, so it works no matter which
PC or browser the auditor used.

**How it runs:** a flow checks the workbook on a schedule (e.g. every 30 min),
finds any Invalid audit not yet emailed, sends the email, and marks it emailed
so it never sends twice.

---

## STEP 0 — One-time workbook prep (data-safe, do this on the LIVE file)

The flow needs an **emailSent** column to remember what it already sent.

1. Open the live workbook in the SharePoint EQMS folder (Excel Online).
2. Go to the **Audit Log** sheet. Click the **first empty cell to the right of
   the `sendEmail` header** (cell **V1**).
3. Type **`emailSent`** and press **Enter**. The table expands to include it —
   done. Leave the column blank; the flow fills it in.

*(If you'd rather not touch the live file, the attached
`EQMS_PowerAutomate_ready.xlsx` already has this column — but replacing the live
file risks losing audits added since. Adding the one cell above is safer.)*

---

## STEP 1 — Create the flow

1. In a browser go to **make.powerautomate.com** and sign in with your
   Concentrix account.
2. Left menu **+ Create** → **Scheduled cloud flow**.
3. Flow name: **EQMS Invalid Audit Emailer**.
   Starting: leave as now. Repeat every: **30 Minute(s)** (your choice: 15–60).
   Click **Create**.

---

## STEP 2 — Read the audit table

1. Click **+ New step** → search **Excel Online (Business)** → choose
   **List rows present in a table**.
2. Fill the boxes (use the dropdowns, don't type):
   - **Location:** the SharePoint site — *Project_Global_Quality-HP Mainstream LOB*
   - **Document Library:** Documents
   - **File:** browse to the **EQMS** folder → your workbook
   - **Table:** **tblAudits**
3. (Optional, makes it faster) click **Show advanced options** → **Filter Query:**
   `validation eq 'Invalid'`

---

## STEP 3 — Loop the invalid, not-yet-emailed rows

1. **+ New step** → **Control** → **Apply to each**.
2. In "Select an output from previous steps", pick **value** (from List rows).
3. Inside the loop: **Add an action** → **Control** → **Condition**. Set:
   - Left box: **Dynamic content → validation**
   - Middle: **is equal to**
   - Right box: `Invalid`
   - Click **+ Add** → **And**. Second row:
     - Left: **Dynamic content → emailSent**
     - Middle: **is not equal to**
     - Right: `Yes`

Everything below goes in the **If yes** branch.

---

## STEP 4 — Send the email

In **If yes** → **Add an action** → **Office 365 Outlook** →
**Send an email (V2)**.

- **To:** Dynamic content **tlEmail**, then type `;`, then Dynamic content **omEmail**
- **Cc:** `PH_QUE_NE_HP_Quality_Support@concentrix.com`  *(your QA DL)*
- **Subject:** type `[INVALID] Quality Audit - ` then insert **agentName**,
  then ` - Case ` then insert **caseNumber**
- **Body:**
  1. Click the little **</> (code view)** button on the Body toolbar.
  2. Open **email_body.html** (attached), select all, copy, paste it in.
  3. Click **</>** again to return to normal view — you'll see the formatted
     table with `«placeholders»`.
  4. Replace each `«placeholder»` by selecting it and inserting the matching
     **Dynamic content** (see mapping below).

**Placeholder → Dynamic content mapping:**

| Replace this | With dynamic content |
|---|---|
| «teamLeader» | teamLeader |
| «agentName» | agentName |
| «auditDate» | auditDate |
| «caseNumber» | caseNumber |
| «genesysTransactionId» | genesysTransactionId |
| «channel» | channel |
| «lob» | lob |
| «auditorName» | auditorName |
| «caseResolution» | caseResolution |
| «expectedResolutionCode» | expectedResolutionCode |
| «remarks» | remarks |

*(agentName and teamLeader appear more than once — replace every instance.)*

**From a shared mailbox instead of yours?** Use **Send an email from a shared
mailbox (V2)** and put the shared address in **Original Mailbox Address** — you
need Send-As rights on it.

---

## STEP 5 — Mark it emailed (so it never sends twice)

Still in **If yes**, below the email: **Add an action** →
**Excel Online (Business)** → **Update a row**.

- **Location / Document Library / File / Table:** same as Step 2 (tblAudits).
- **Key Column:** **auditId**
- **Key Value:** Dynamic content **auditId**
- Scroll to the **emailSent** field → type **`Yes`**

---

## STEP 6 — Save and test

1. Top-right **Save**.
2. Click **Test** → **Manually** → **Test** → **Run flow**.
3. Make sure at least one audit in the log is **Invalid** with a blank
   emailSent. Within a few seconds the TL/OM get the formatted email, and that
   row's **emailSent** flips to **Yes**.
4. From now on it runs every 30 minutes on its own. Watch runs under
   **My flows → EQMS Invalid Audit Emailer → run history** (a green check per run).

---

## Notes & troubleshooting

- **Timing:** emails go out within your chosen interval (worst case ~30 min),
  not the instant the row is typed — Excel has no reliable "on new row" trigger,
  so the flow polls on a schedule.
- **"Update a row" fails / permission error:** the Audit Log sheet protection is
  blocking the write. In Excel: **Review → Unprotect Sheet** (the emailSent
  column was left unlocked, but if it still blocks, unprotect once).
- **No email arrives but run is green:** check the TL/OM email cells aren't blank
  for that agent (fix the Roster), and check your Junk folder on first send.
- **Don't want an email for older backfilled audits:** before turning the flow
  on, type `Yes` in emailSent for every existing row you don't want emailed.
- **Editing the email later:** just open the flow, tweak the Body, Save. No file
  changes needed.
