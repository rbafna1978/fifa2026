.PHONY: setup run run-adk eval-naive eval-reflect demo-loop help

help:
	@echo "Targets:"
	@echo "  make setup        - uv sync + remind to copy .env"
	@echo "  make run          - one-shot traced run (MESSAGE=...)"
	@echo "  make run-adk      - ADK CLI dev loop (cd agent && adk run shopping_demo)"
	@echo "  make eval-naive   - plan WITHOUT reflection -> low eval score (the 'before')"
	@echo "  make eval-reflect - agent reads its own eval history, then plans -> high score (the 'after')"
	@echo "  make demo-loop    - full before/after: naive, naive, reflect + summary (demo video)"

setup:
	uv sync
	@test -f .env || echo "Tip: copy .env.example to .env and add keys."

run:
	cd agent && uv run python main.py "$(if $(MESSAGE),$(MESSAGE),Help me find a floral summer dress and buy size M.)"

run-adk:
	cd agent && uv run adk run shopping_demo

eval-naive:
	cd agent && uv run python run_eval.py naive

eval-reflect:
	cd agent && uv run python run_eval.py reflect

demo-loop:
	cd agent && uv run python run_eval.py demo
