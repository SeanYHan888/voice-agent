# Lesson 2 — The Six Containers

## 2. The six containers

**Definition:** A container is an isolated runtime process with its own program, dependencies, network address, and responsibility.

| Container | Runtime | Owns |
|---|---|---|
| `gateway` | Nginx on port 80 | Public routing and forwarded request metadata |
| `frontend` | Nginx serving a Vite build | React pages and browser interactions |
| `auth` | FastAPI/Uvicorn on port 8000 | Portal accounts, password checking, and JWT creation |
| `domain` | FastAPI/Uvicorn on port 8000 | Patients, scheduling, calls, FAQ data, and business rules |
| `agent` | FastAPI/Uvicorn on port 8000 | Maya, LangGraph, tools, guardrails, and voice adapters |
| `postgres` | PostgreSQL 16 with pgvector | Durable relational data, vectors, and graph checkpoints |

Two ownership rules prevent architectural confusion:

- Agent decides what Maya should say or which structured operation to request.
- Domain decides what is true, what is permitted, and which records change.

The frontend container only serves compiled files. React runs in the user's browser after those files are downloaded. The Gateway is the application's public HTTP entrance; the other application containers communicate over Docker's private network.

### Code example — List the configured services

**Predict first:** Predict the six service names and their order before running the command.

```bash
docker compose config --services
```

Expected names:

```shell
postgres
auth
domain
agent
frontend
gateway
```

**Trace it:** Compose reads `docker-compose.yml`, resolves the top-level `services` keys, and prints each service name. This shows deployment units without starting or changing them.

**What to notice:** Repository folders are not the runtime boundary by themselves; each Compose service becomes a separately addressable process.

**Try changing:** Add `--images` instead of `--services` and explain why the output changes from logical service names to image names.

**Next:** Knowing the processes lets us follow how one public URL selects a specific service.
