# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Initial setup
npm run setup          # install deps + prisma generate + prisma migrate dev

# Development
npm run dev            # start dev server with Turbopack at localhost:3000
npm run dev:daemon     # start in background, logs → logs.txt

# Build & production
npm run build
npm start

# Code quality
npm run lint           # Next.js ESLint

# Tests
npm test               # run all Vitest tests
npx vitest run <path>  # run a single test file

# Database
npm run db:reset       # reset and re-migrate SQLite (destructive)
npx prisma studio      # browse database in browser
```

**Environment:** Copy `.env` and set `ANTHROPIC_API_KEY`. The app works without it — a mock provider returns static components.

## Architecture

### Three-panel UI

`src/app/main-content.tsx` renders a resizable split layout:
- **Left (35%):** Chat interface (`components/chat/`)
- **Right (65%):** Preview (`components/preview/PreviewFrame.tsx`) **or** Code view — file tree (`components/editor/FileTree.tsx`) + Monaco editor (`components/editor/CodeEditor.tsx`)

### Data flow

1. User types a message → `ChatProvider` (`lib/contexts/chat-context.tsx`) sends it to `POST /api/chat`
2. The route (`src/app/api/chat/route.ts`) calls Claude via Vercel AI SDK `streamText()` with two tools:
   - `str_replace_editor` (`lib/tools/str-replace.ts`) — targeted edits to existing files
   - `file_manager` (`lib/tools/file-manager.ts`) — create/delete files
3. Tool calls mutate the **virtual file system** (`lib/file-system.ts`), an in-memory tree held in `FileSystemProvider` (`lib/contexts/file-system-context.tsx`)
4. On stream completion the route serialises messages + FS state and upserts the `Project` row in SQLite via Prisma

### AI provider

`lib/provider.ts` returns the language model used for generation:
- **With API key:** Claude Haiku 4.5, up to 40 tool-call steps
- **Without API key:** `MockLanguageModel` — returns a static Counter/Form/Card component, 4 steps max

The system prompt lives in `lib/prompts/generation.tsx`.

### Virtual file system

`lib/file-system.ts` is a pure in-memory tree — nothing is written to disk. It is serialised to JSON and stored in `Project.data` (SQLite). The Monaco editor and preview frame both read from this tree.

### Auth

JWT sessions via `jose` (7-day, HttpOnly cookie). Passwords hashed with bcrypt. Server actions and the chat route call `getUser()` from `lib/auth.ts` to resolve the current user. Auth UI lives in `components/auth/`.

### Routing

- `/` — home; redirects authenticated users to their latest project (or creates one)
- `/[projectId]` — loads a project from DB and hydrates `MainContent` with saved messages + FS state
- `/api/chat` — streaming POST endpoint

### Database (Prisma + SQLite)

Schema: `User` (email, password) → many `Project` (name, `messages` JSON blob, `data` JSON blob). Generated client is at `src/generated/prisma/`.

### Node compatibility shim

`node-compat.cjs` is required before Next.js starts (see `NODE_OPTIONS` in all npm scripts). It removes `localStorage`/`sessionStorage` globals added in Node 25+ that break SSR.
