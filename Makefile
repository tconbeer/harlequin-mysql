.PHONY: check
check:
	uv run ruff format .
	uv run ruff check . --fix
	uv run mypy
	uv run pytest

.PHONY: init
init:
	docker-compose up -d

.PHONY: clean
clean:
	docker-compose down

.PHONY: serve
serve:
	uv run harlequin -P None -a mysql -h localhost -U root --password example --database dev
