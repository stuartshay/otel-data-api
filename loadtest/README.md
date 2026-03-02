# Locust Load Testing

Load test suite simulating real `otel-data-ui` user journeys against the
`otel-data-api` REST API.

## User Personas

| Persona | Weight | Description |
|---------|--------|-------------|
| LocationBrowser | 4 | Browse OwnTracks locations, devices, counts |
| GarminExplorer | 3 | View cycling activities, track points, charts |
| MapViewer | 3 | Unified GPS map, daily summary, references |
| SpatialAnalyst | 2 | Nearby points, distance, within-reference |

## Quick Start

```bash
# Run locally (Python)
pip install locust
locust -f locustfile.py --host https://api.lab.informationcart.com

# Run with Docker Compose
docker compose up -d
# Open http://localhost:8089

# Headless mode (CI/Semaphore)
docker compose run --rm master \
  -f /mnt/locust/locustfile.py \
  --headless \
  --host https://api.lab.informationcart.com \
  --users 10 \
  --spawn-rate 2 \
  --run-time 5m \
  --csv /mnt/locust/results
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCUST_USERS` | 10 | Number of concurrent users |
| `LOCUST_SPAWN_RATE` | 2 | Users spawned per second |
| `LOCUST_RUN_TIME` | 5m | Test duration |

## Semaphore Integration

Use the Ansible playbook to run load tests on-demand via Semaphore:

```bash
ansible-playbook playbooks/load-testing/locust-runner.yml \
  -e locust_users=10 \
  -e locust_spawn_rate=2 \
  -e locust_run_time=5m
```
