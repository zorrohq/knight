CREATE TABLE IF NOT EXISTS agent_branches (
    id BIGSERIAL PRIMARY KEY,
    repository TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    base_branch TEXT NOT NULL,
    agent_branch TEXT NOT NULL,
    pr_number INTEGER,
    provider TEXT NOT NULL DEFAULT 'github',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT agent_branches_status_check
        CHECK (status IN ('open', 'pushed', 'merged', 'closed', 'failed')),
    CONSTRAINT agent_branches_repo_issue_branch_unique
        UNIQUE (repository, issue_id, agent_branch)
);

CREATE INDEX IF NOT EXISTS agent_branches_repo_issue_status_idx
    ON agent_branches (repository, issue_id, status);

CREATE INDEX IF NOT EXISTS agent_branches_agent_branch_idx
    ON agent_branches (agent_branch);

-- No seed rows are currently required. This file exists to create the
-- schema and indexes needed by the worker state store.
