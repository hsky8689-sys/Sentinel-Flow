# 🚀 Backend for Sentinel Flow

Django/Channels backend powering **Sentinel Flow**, a project-orchestration platform for teams shipping software across one or more Git repositories.

---

### 1. 🛠️ Local Setup Guide

**Prerequisite 1 — Redis** (cache backend + Channels layer):

```bash
docker run -d --name sentinel-redis -p 6379:6379 redis:7-alpine
```

**Prerequisite 2 — Python environment**:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Populate a .env file at the project root (DB_*, REDIS_URL, SECRET_KEY,
# GITHUB_TOKEN, RAPIDAPI_*, JWT_* — see devnetwork/settings.py for the
# full list read via python-decouple)

python manage.py migrate
```

**Prerequisite 3 — Run the server**:

```bash
python manage.py runserver
```

---

### 2. 🎯 Problem Statement & Core Solution

Sentinel Flow solves the coordination overhead of running non-trivial software projects with distributed ownership:

- **Multi-repo project orchestration** — a `Project` isn't tied to a single Git repository; it aggregates any number of linked repos (`ProjectRepoStats`), each with its own branch-protection state and access token, under one project-level permission model.
- **Granular concurrency control** — a strict single-writer file-locking mechanism (`ResourceAccess`) enforces **one user at a time per file, per project**, eliminating merge conflicts at the source instead of resolving them after the fact.
- **Built-in inter-user communication** — a WebSocket-backed chat layer (Django Channels) supports 1-on-1 conversations, ad-hoc group conversations, and conversations scoped to a specific project, so collaboration never has to leave the platform.

---

### 3. 🌐 REST API Design & Security Hardening

- **Predictable REST surface** — resource-oriented URL patterns (`/projects/settings/<id>/tasks`, `/projects/settings/<id>/roles`, `/chat/conversations/projects/<id>`, …) with uniform JSON request/response contracts across `users`, `projects`, and `chat`.
- **Multi-layered security, enforced per-endpoint**:
  - **Rate limiting** (`django-ratelimit`) keyed independently by user, IP, or a combination, tuned per endpoint (auth endpoints throttle harder than read-heavy ones) to blunt brute-force and DoS attempts.
  - **Session-based authentication** (`login_required`) gating every non-public endpoint; JWT issuance/refresh/blacklist endpoints are also exposed for API-client use cases.
  - **CSRF protection** on every state-changing session-authenticated route, deliberately exempted only where the caller is an external system authenticated by its own signature (GitHub webhooks — see §6).
- Backed by an **automated test suite** exceeding 300 cases covering authorization boundaries, rate-limit thresholds, and external API integrations against mocked HTTP calls (no live GitHub/Judge0 traffic).

---

### 4. 🔑 Customizable ReBAC & Task Affiliation

- **Relationship-Based Access Control** — permissions aren't a fixed global enum; each project defines its own `ProjectRole` set (owner, admin, or fully custom roles created via the API) with granular flags — `can_create_branches`, `can_modify_files`, `can_execute_code`, `can_change_project_settings`, and more — evaluated in the context of that specific project relationship, not the user globally.
- **Task-scoped resource affiliation** — `ProjectTask` entities are affiliated with both the users who own them (`ProjectTaskParticipation`) and the exact file paths they cover (`TaskResourceAccess`). File-level authorization for non-privileged members resolves through task participation rather than a blanket role, so access stays scoped to what a contributor is actually working on.

---

### 5. ⚡ Scalable Caching Strategy

- **Cache-aside pattern on Redis** for the platform's hottest reads — profile sections, tech-stack listings, project role/permission lookups, conversation lists, and linked-repo summaries are all served from cache first, falling through to Postgres only on a miss.
- **Strict write-invalidation** — every mutating operation explicitly deletes its corresponding cache key(s) at write time, guaranteeing the next read is never stale rather than relying on TTL expiry alone.
- The cache layer degrades gracefully: a Redis outage falls back to direct DB reads instead of taking the request down, by design.

---

### 6. 🎣 Git Integration, Audit Logging & Webhook Handlers

- **Audit trail** — every push executed through the platform is recorded (`AuditLogAction`), giving a per-project, per-user history of write activity to a linked repository.
- **Controlled mutation** — when a project enables app-only pushes, branch protection is applied via the GitHub API and every commit pushed through Sentinel Flow is stamped with an HMAC-signed trailer, so provenance can be verified independently of who's asking.
- **Out-of-band push handling** — a dedicated webhook endpoint (HMAC-verified against `X-Hub-Signature-256`) inspects every incoming push event, cross-checks each commit's signature trailer, and flags the project the moment a commit bypasses the platform — without disrupting projects that don't opt into app-only mode.
