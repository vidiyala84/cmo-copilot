# CMO Copilot backend — FastAPI over the three tracks + the 100-question benchmark.
# Deploy on Alibaba Cloud (ECS / Function Compute / SAE). Uses Qwen on Alibaba
# Cloud Model Studio (DashScope) via config.py/llm.py — LLM_PROVIDER=dashscope.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r api/requirements.txt

COPY . .

# Build the deterministic dataset at image time so first request is fast.
RUN python -m cmo.datagen

ENV STAGE=prod LLM_PROVIDER=dashscope
# DASHSCOPE_API_KEY is injected at deploy time (env var / secret), never baked in.
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
