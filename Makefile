.PHONY: check
check:
	poetry run ruff format .
	poetry run ruff check . --fix
	poetry run mypy
	poetry run pytest

.PHONY: init
init:
	docker-compose up -d

.PHONY: clean
clean:
	docker-compose down

.PHONY: serve
serve:
	poetry run harlequin -P None -a mysql -h localhost -U root --password example --database dev
