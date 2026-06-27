.PHONY: up down restart build pull logs shell migrate ps clean

COMPOSE = docker compose
APP     = app

## Build image and start all services
up:
	$(COMPOSE) up -d --build

## Stop and remove containers (volumes are preserved)
down:
	$(COMPOSE) down

## Restart a service  — usage: make restart  or  make restart s=celery
restart:
	$(COMPOSE) restart $(or $(s),$(APP))

## Rebuild the image without starting
build:
	$(COMPOSE) build $(APP)

## Pull the latest image from GHCR (skip local build)
pull:
	$(COMPOSE) pull

## Follow logs  — usage: make logs  or  make logs s=celery
logs:
	$(COMPOSE) logs -f $(or $(s),$(APP))

## Open a shell inside the running app container
shell:
	$(COMPOSE) exec $(APP) /bin/bash

## Run pending Alembic migrations manually
migrate:
	$(COMPOSE) exec $(APP) alembic upgrade head

## Show container status
ps:
	$(COMPOSE) ps

## Remove containers AND all volumes (destructive — deletes DB + Redis data)
clean:
	@echo "WARNING: this deletes all data. Press Ctrl-C to abort, Enter to continue." && read _
	$(COMPOSE) down -v
