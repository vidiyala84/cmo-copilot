# Deploying CMO Copilot on Alibaba Cloud

The hackathon requires the backend to run on **Alibaba Cloud** and to use **Qwen on
Qwen Cloud / Model Studio**. CMO Copilot already satisfies the *service-usage* half — every
live decision calls Qwen through Alibaba Cloud Model Studio (DashScope) via
`config.py` / `llm.py` (`LLM_PROVIDER=dashscope`). This is the *deployment* half: run
the FastAPI backend (`api/main.py`) on Alibaba Cloud. Any one of the options below is
sufficient "proof of Alibaba Cloud deployment."

## What runs
`api/main.py` — a FastAPI app exposing the three tracks, the live 7-approach benchmark,
the scaling test, and per-decision traces. It imports the same modules the CLI uses, so
one image serves everything.

## The one secret
`DASHSCOPE_API_KEY` (your Qwen Cloud / Model Studio key). **Injected at deploy time as an
environment variable — never baked into the image or committed.**

---

## Option A — Alibaba Cloud ECS (simplest, ~10 min)

1. Create an ECS instance (Ubuntu 22.04, 2 vCPU / 4 GB is plenty), open port 8000 in its
   Security Group.
2. Install Docker, then on the instance:
   ```bash
   git clone https://github.com/vidiyala84/cmo-copilot.git && cd cmo-copilot
   docker build -t cmo-copilot .
   docker run -d --name cmo --restart unless-stopped \
     -p 8000:8000 -e DASHSCOPE_API_KEY="sk-..." cmo-copilot
   ```
   `--restart unless-stopped` keeps it up across reboots — matters for a judging window
   that runs for weeks.
3. Verify: `curl http://<ECS-public-ip>:8000/api/health` → `{"ok":true,"provider":"dashscope","models":{...},"live_available":true}` (`live_available:true` confirms the DASHSCOPE key reached the container).
   Open `http://<ECS-public-ip>:8000/` in a browser for the landing page — that's the shot for the submission.

That public URL (calling Qwen on Model Studio) is the deployment proof — screenshot it for
the submission.

### Cap the spend (do this before judging opens)
The static routes (`/`, `/api/health`, `/api/scenarios`) make **zero** Qwen calls, but a
judge triggering a *live* run does. In the Model Studio console set a **billing spending
limit** on the DASHSCOPE key so unattended usage can't run up a bill. Compute-wise, prefer a
**burstable (t-series) 2 vCPU/4 GB monthly subscription** with **pay-by-traffic** bandwidth
— roughly $20–40 for the month, often covered by new-user free credits.

## Option B — Alibaba Cloud Function Compute (serverless, container image)

1. Push the image to **Alibaba Cloud Container Registry (ACR)**:
   ```bash
   docker build -t cmo-copilot .
   docker tag cmo-copilot registry.<region>.aliyuncs.com/<namespace>/cmo-copilot:latest
   docker push registry.<region>.aliyuncs.com/<namespace>/cmo-copilot:latest
   ```
2. In **Function Compute**, create a container-image function from that image, port 8000,
   and set `DASHSCOPE_API_KEY` as an environment variable.
3. The function's HTTP trigger URL is the deployment proof.

## Option C — Serverless App Engine (SAE)

Deploy the same image on **SAE** as a web app, expose port 8000, set `DASHSCOPE_API_KEY`
as an env var, and use the assigned public endpoint.

---

## The "code file demonstrating Alibaba Cloud service usage" (for the submission form)
Point the judges at **`config.py`** (the `dashscope` provider block: base URL
`dashscope-intl.aliyuncs.com/compatible-mode/v1`, `DASHSCOPE_API_KEY`) and **`llm.py`**
(`default_live_llm` → the OpenAI-compatible client against Model Studio). Every live run
in the repo goes through this path.

## Local smoke test before deploying
```bash
docker build -t cmo-copilot . && docker run -p 8000:8000 -e DASHSCOPE_API_KEY="sk-..." cmo-copilot
curl http://localhost:8000/api/health
```
