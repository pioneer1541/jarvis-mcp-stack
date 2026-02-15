FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
  "mcp>=1.10,<2" \
  "uvicorn[standard]>=0.30,<1" \
  "starlette>=0.37,<1" \
  "requests>=2.31,<3"

# Install optional deps from requirements.txt (e.g., holidays for holiday_vic)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY news.py /app/news.py
COPY calendar.py /app/calendar.py
COPY music.py /app/music.py
COPY answer.py /app/answer.py
COPY router_helpers.py /app/router_helpers.py
COPY router_pipeline.py /app/router_pipeline.py
COPY openai_compat_gateway.py /app/openai_compat_gateway.py
COPY evaluation /app/evaluation
COPY scripts /app/scripts

EXPOSE 19090

CMD ["python", "/app/app.py"]
