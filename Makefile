.PHONY: check
check:
	ruff format .
	ruff . --fix
	mypy
	pytest

.PHONY: init
init:
	docker-compose up -d

.PHONY: clean
clean:
	docker-compose down

.PHONY: serve
serve:
	harlequin -P None -a mysql -h localhost -U root --password example --database dev
