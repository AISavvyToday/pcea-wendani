# Release Checklist (Local + CI)

All commands below are **required to pass before deployment**.
If any command fails, deployment must be blocked until fixed.

## Local

```bash
./scripts/release_checklist.sh
```

## CI command set

Run the same gate in CI:

```bash
bash ./scripts/release_checklist.sh
```

## Included checks

1. `python manage.py check`
2. `python manage.py test reports.tests_regression`
3. `python manage.py test payments.tests.test_services payments.tests.test_views`
4. `python manage.py test students.tests`
