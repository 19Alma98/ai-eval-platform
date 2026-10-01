# Frontend Technical Specification

## Stack

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- ECharts/Recharts
- Playwright

## Visual direction

Reference principles:
- Linear-like density
- Vercel-like typography/spacing
- observability-grade charts
- restrained color usage
- dark/light themes
- keyboard-first navigation

The UI should feel like a developer platform console, not an admin template or multi-tenant SaaS product shell.

No login/signup screens are required for v0.1. The UI assumes a trusted local or privately deployed instance.

## Primary screens

### 1. Overview

Metrics:
- quality
- latency
- cost
- error rate
- recent regressions

### 2. Trace Explorer

Features:
- waterfall
- span tree
- attributes
- input/output with redaction indicators
- token/cost metrics
- evaluation results

### 3. Dataset

Features:
- examples
- filters
- labels
- human review
- add-from-trace

### 4. Experiments

Features:
- run status
- evaluator results
- metric distributions
- baseline comparison
- regression markers

### 5. Release Check

A GitHub-like result:
- PASS/FAIL
- failed checks
- delta
- threshold
- link to affected samples

## Design system

Define:
- spacing scale
- typography
- status semantics
- chart conventions
- empty states
- loading states
- error states

Avoid excessive dashboard cards.

## Accessibility

Target WCAG 2.2 AA where practical:
- keyboard navigation
- focus states
- semantic controls
- contrast
- reduced motion
