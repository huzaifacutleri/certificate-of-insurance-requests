# Working in this repository

COI Assistant: certificate-of-insurance request automation. Read `README.md` and
`docs/ARCHITECTURE.md` first.

## Commands

```bash
pip install -e ".[dev,api,llm]"   # full dev environment
pytest                            # offline, under a second
ruff check . && ruff format .     # lint + format (line length 100)
python -m coi demo                # end-to-end smoke run
```

## Rules that must not be broken

1. **Certificates are built from policy data only.** Never copy text from an email into
   certificate content or coverage claims. See `validation.build_draft`.
2. **A human approves every certificate.** Do not add any path that sends or finalizes a
   certificate without `Workflow.approve`.
3. **Never guess a client.** Ambiguous or unknown insured names must reach a human.
4. **`validation.py` stays pure** (no I/O, no clock; `today` is a parameter) and every rule has
   a test in `tests/test_validation.py`.
5. **Every query is scoped by `agency_id`** through `Repository`.
6. **Examples stay synthetic.** Never commit real client names, policy numbers or emails.

## Conventions

- Python 3.11+, type hints everywhere, pydantic models for data that crosses a boundary.
- Comment *why*, not what. Docstring every module and public function.
- Core modules must not import FastAPI or the Anthropic SDK; those stay in `api.py` and
  `extraction/llm.py` (the SDK import is lazy).
- Add a test with every behavior change. Mutation-check important rules by temporarily breaking
  them and confirming a test fails.
