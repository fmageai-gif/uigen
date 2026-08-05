# How to run the Case Queue

Step-by-step, from nothing installed to the app open in your browser.
Written for Windows (PowerShell), but the commands are the same on Mac.

---

## One time only

### 1. Install Node.js

Download the **LTS** version from https://nodejs.org and run the installer.

Click Next through the screens, with **one exception**. Near the end there is
a checkbox:

> Automatically install the necessary tools for Node.js modules that require
> compilation (Python, Visual Studio Build Tools, chocolatey)

**Leave it unchecked.** Checking it launches a separate Visual Studio
installer that takes a very long time, often fails on corporate networks, and
is not needed for this app.

If you already checked it and a blue window full of `Warning:` and
`Failed to download` lines is running — just close that window. Node.js
itself installed before it opened; that extra step is optional.

Then open **PowerShell** (Start menu → type "PowerShell" → Enter) and check
it worked:

```powershell
node --version
```

You should see something like `v22.22.0`. Any number 18 or higher is fine.
If you get "not recognized", close PowerShell, open it again, and retry —
the installer needs a fresh window.

### 2. Install Git

Download from https://git-scm.com/download/win, run it, accept the defaults.
Check it:

```powershell
git --version
```

### 3. Get the code

This downloads the project into a `uigen` folder inside your Documents:

```powershell
cd ~\Documents
git clone https://github.com/fmageai-gif/uigen.git
cd uigen
git checkout claude/app-build-case-list-pdhsxo
```

That last line matters — it switches to the branch with the Case Queue on it.

### 4. Install and set up

```powershell
npm run setup
```

Takes a couple of minutes. It installs dependencies and creates the local
database. Warnings in yellow are normal; only red `ERR!` lines are problems.

### 5. Load the cases

```powershell
npm run db:seed-cases
```

You should see:

```
Seeded 16 cases. Table now holds 16 (1 opened).
```

"1 opened" is correct — case `5163090341` was opened before the app existed.

---

## Every time you want to use it

Open PowerShell and run:

```powershell
cd ~\Documents\uigen
npm run dev
```

Wait for `Ready in ...`, then open your browser to:

**http://localhost:3000/cases**

To stop it: click back on the PowerShell window and press **Ctrl + C**.

Leave that window open while you're using the app — closing it stops the app.

---

## Using it

- Each row is a case. Click **Open** to claim one.
- The row locks, greys out, and shows when you opened it. The button is gone
  for good — that case can't be opened again.
- The counters up top show how many are left and how many you've done.
- The search box filters by case ID or subject.

Your opens are saved to the local database file, so they survive closing the
app and restarting your computer.

---

## Coming back after I push changes

When new work lands on the branch:

```powershell
cd ~\Documents\uigen
git pull origin claude/app-build-case-list-pdhsxo
npm install
npx prisma migrate deploy
npm run dev
```

This keeps the cases you've already opened.

---

## If something goes wrong

**"port 3000 is already in use"** — the app is already running in another
window. Either use that one, or close it and try again.

**"npm is not recognized"** — Node.js isn't installed, or PowerShell needs
restarting after installing it. Go back to step 1.

**"npm.ps1 cannot be loaded because running scripts is disabled on this
system"** — Windows blocks PowerShell scripts by default, and npm is one.
Fix it once for your own account:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Press `Y` then Enter when it asks. Now `npm` works normally, in this window
and every future one.

If you would rather not change the setting, add `.cmd` to every npm command
instead — `npm.cmd run setup`, `npm.cmd run dev`. Same result, but you have
to remember it every time.

**The page is blank or errors** — stop with Ctrl + C, then:

```powershell
npx prisma generate
npm run dev
```

**You want to wipe all opens and start over** — this deletes every opened
record and reloads the 16 cases from scratch:

```powershell
npm run db:reset
npm run db:seed-cases
```

Only do this deliberately. It cannot be undone.
