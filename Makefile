# make data | parse | results | train-demo | tune | test | score | report | demo | test-unit
PY ?= .venv/Scripts/python
COMPOSE = docker compose -f deploy/docker-compose.yml

data:
	$(PY) scripts/download_data.py

parse:
	$(PY) -m logpulse.parsing.drain_parser --dataset hdfs --sim-th 0.5
	$(PY) -m logpulse.parsing.drain_parser --dataset bgl --sim-th 0.5

results:
	$(PY) scripts/run_all_experiments.py --config configs/experiments.yaml

demo:
	$(COMPOSE) up -d fluent-bit
	$(COMPOSE) --profile deploy build
	$(COMPOSE) up -d --build
	$(COMPOSE) --profile deploy create payment-v2

normal:
	$(PY) scripts/run_live_protocol.py normal --minutes 30

train-demo:
	$(PY) -m logpulse.online.train_demo --run normal
	$(COMPOSE) restart detector

tune:
	$(PY) scripts/run_live_protocol.py tune
	$(PY) -m logpulse.online.tune_demo --runs tune_s1 tune_s2 --deploy-run tune_deploy
	$(COMPOSE) restart detector

test:
	$(PY) scripts/run_live_protocol.py test

score:
	$(PY) scripts/score_live.py
	$(PY) -m logpulse.eval.tables
	$(PY) scripts/incident_report.py --all

report:
	$(PY) scripts/make_report.py

test-unit:
	$(PY) -m pytest -q
