# LunaGrow BioSim client — thin Python REST driver.
# This does NOT run BioSim itself; see docker-compose.yml, which builds the
# real BioSim server from https://github.com/scottbell/biosim as a sibling
# service and waits for it to be healthy before this container starts.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lunagrow_biosim/ ./lunagrow_biosim/
COPY wait_and_run.py .

# Results land here; mount a host volume over it in docker-compose.yml
# so CSVs survive after the container exits.
RUN mkdir -p /app/results

ENTRYPOINT ["python", "wait_and_run.py"]
CMD ["--scenario", "all", "--sols", "100", "--url", "http://biosim-server:8009/api/simulation"]
