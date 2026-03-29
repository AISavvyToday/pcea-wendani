#!/usr/bin/env bash
set -euo pipefail

# Release quality gate for local and CI usage.

commands=(
  "python manage.py check"
  "python manage.py test reports.tests_regression"
  "python manage.py test payments.tests.test_services payments.tests.test_views"
  "python manage.py test students.tests"
)

echo "Running release checklist..."
for cmd in "${commands[@]}"; do
  echo "→ $cmd"
  eval "$cmd"
done

echo "All release checklist commands passed. Safe to deploy."
