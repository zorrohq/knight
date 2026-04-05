# Knight — Project Context

## Overview

Knight is a background agent system designed to autonomously execute development tasks on software repositories. The system receives tasks via webhooks or API calls, executes an AI coding agent in an isolated environment, modifies the repository, runs verification steps, and produces changes such as commits or pull requests.

The objective is to build a minimal, infrastructure-first autonomous coding worker capable of operating asynchronously and safely against real repositories.

Knight focuses on backend orchestration, sandboxed execution, and automated Git workflows rather than user-facing interfaces.

---

# Core Concept

Knight acts as an automated engineering worker.

It accepts a task describing work to be done on a repository and performs the following pipeline:

trigger → queue → orchestrator → sandbox → coding agent → validation → git commit / PR

Typical tasks include:

* implementing features
* fixing bugs
* refactoring code
* generating documentation
* updating dependencies
* responding to issue tickets

---

# System Responsibilities

Knight must provide the following capabilities:

1. Task ingestion from external systems.
2. Asynchronous job scheduling.
3. Repository cloning and workspace preparation.
4. Sandboxed execution environments.
5. Agent-driven code modification.
6. Build and test verification.
7. Git operations and pull request generation.

The system is designed to run continuously as a background worker.

---

# High-Level Architecture

External Trigger (Webhook / API)
↓
FastAPI service
↓
Task queue (Celery + Redis or RabbitMQ)
↓
Worker node
↓
Sandbox runtime (Docker or VM)
↓
Agent execution loop
↓
Git operations (commit / PR)

---

# Execution Flow

1. External service sends a webhook containing a task.
2. FastAPI endpoint validates and queues the task.
3. Celery worker retrieves the task.
4. Worker prepares an isolated runtime environment.
5. Repository is cloned into the workspace.
6. Coding agent analyzes repository and plans changes.
7. Agent edits files and runs commands.
8. System runs verification (tests/build/lint).
9. Changes are committed to a new branch.
10. Pull request is created through Git provider API.

---

# Initial Scope

The first version of Knight focuses on the minimal viable system.

Included features:

* webhook ingestion
* Celery-based task queue
* single-node worker
* Docker-based sandbox runtime
* repository cloning
* basic coding agent execution
* pull request creation

Not included initially:

* distributed worker scheduling
* complex planning agents
* UI dashboards
* multi-tenant isolation
* advanced sandbox orchestration

---

# Repository Structure

The project follows a Python src-layout.

```
knight/
│
├─ pyproject.toml
├─ README.md
├─ context.md
│
├─ src/
│  └─ knight/
│     │
│     ├─ api/
│     │  ├─ server.py
│     │  └─ routes/
│     │     └─ webhook.py
│     │
│     ├─ queue/
│     │  └─ celery_app.py
│     │
│     ├─ orchestrator/
│     │  └─ dispatcher.py
│     │
│     ├─ runtime/
│     │  ├─ docker_runtime.py
│     │  └─ workspace.py
│     │
│     ├─ agents/
│     │  ├─ coding_agent.py
│     │  └─ prompts/
│     │
│     ├─ git/
│     │  ├─ repo_manager.py
│     │  └─ github_client.py
│     │
│     ├─ tasks/
│     │  └─ run_agent_task.py
│     │
│     └─ config.py
│
├─ workers/
│  └─ worker.py
│
└─ tests/
```

---

# Key Components

## API Layer

FastAPI service responsible for:

* receiving webhook events
* validating task payloads
* pushing tasks to the queue

This layer should remain thin and stateless.

---

## Queue System

Celery is used to handle asynchronous task execution.

Responsibilities:

* scheduling tasks
* retry logic
* worker distribution
* job persistence

Redis or RabbitMQ will act as the broker.

---

## Worker

Workers consume tasks and run the full execution pipeline.

Responsibilities:

* workspace preparation
* sandbox startup
* agent execution
* verification steps
* git operations

Workers are designed to run independently and scale horizontally.

---

## Runtime / Sandbox

Each task runs inside an isolated workspace.

Initial implementation uses Docker containers.

Responsibilities:

* create ephemeral workspaces
* clone repository
* run commands safely
* destroy environment after execution

Future versions may replace Docker with microVM solutions such as Firecracker.

---

## Agent

The coding agent is responsible for repository reasoning and code modification.

Agent loop:

1. analyze repository
2. generate plan
3. modify files
4. run commands
5. inspect results
6. iterate until task completion

The agent interacts with the filesystem and command runner through tool interfaces.

---

## Git Integration

Knight must automate repository workflows.

Capabilities include:

* cloning repositories
* creating branches
* committing changes
* pushing branches
* opening pull requests
* updating existing PRs

GitHub is the initial provider.

---

# Design Principles

Knight follows several architectural principles:

* infrastructure-first design
* strict isolation between tasks
* asynchronous execution
* modular agent architecture
* clear separation between orchestration and execution

The system should behave closer to a CI worker than a traditional application server.

---

# Long-Term Direction

Future iterations may add:

* multi-repository orchestration
* distributed worker clusters
* advanced planning agents
* environment caching
* interactive task updates
* integrations with issue trackers and messaging platforms

The long-term vision is a fully autonomous development worker that continuously processes engineering tasks in the background.

---

# Summary

Knight is an autonomous coding worker platform that accepts development tasks, executes AI agents in isolated environments, and produces repository changes automatically. The system combines asynchronous task processing, sandboxed execution, and automated Git workflows to create a background engineering agent capable of operating continuously without direct human interaction.

