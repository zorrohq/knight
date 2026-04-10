DO $$
BEGIN
    CREATE TYPE app_config_scope AS ENUM ('global', 'repository');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

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

CREATE TABLE IF NOT EXISTS app_config (
    id BIGSERIAL PRIMARY KEY,
    scope app_config_scope NOT NULL DEFAULT 'global',
    repository TEXT,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT app_config_scope_repository_check
        CHECK (
            (scope = 'repository' AND repository IS NOT NULL)
            OR (scope <> 'repository' AND repository IS NULL)
        ),
    CONSTRAINT app_config_scope_key_repository_unique
        UNIQUE (scope, key, repository)
);

CREATE INDEX IF NOT EXISTS app_config_scope_key_idx
    ON app_config (scope, key);

CREATE INDEX IF NOT EXISTS app_config_repository_key_idx
    ON app_config (repository, key)
    WHERE repository IS NOT NULL;

DELETE FROM app_config
WHERE scope = 'global'
  AND key IN ('default_base_branch', 'default_push_remote');

INSERT INTO app_config (scope, repository, key, value, description)
VALUES
    (
        'global',
        NULL,
        'agent_provider',
        '""'::jsonb,
        'Model provider used by the coding agent.'
    ),
    (
        'global',
        NULL,
        'agent_model',
        '""'::jsonb,
        'Model name used by the coding agent.'
    ),
    (
        'global',
        NULL,
        'agent_temperature',
        '0.0'::jsonb,
        'Sampling temperature used by the coding agent.'
    ),
    (
        'global',
        NULL,
        'agent_max_steps',
        '12'::jsonb,
        'Maximum number of model/tool iterations for the coding agent.'
    ),
    (
        'global',
        NULL,
        'agent_command_timeout_seconds',
        '300'::jsonb,
        'Maximum shell command runtime for the coding agent.'
    ),
    (
        'global',
        NULL,
        'agent_max_command_output_chars',
        '12000'::jsonb,
        'Maximum stdout/stderr characters captured from agent-run shell commands.'
    ),
    (
        'global',
        NULL,
        'agent_blocked_command_prefixes',
        '["rm", "sudo", "shutdown", "reboot", "mkfs", "dd"]'::jsonb,
        'Command prefixes blocked by the sandbox policy.'
    ),
    (
        'global',
        NULL,
        'agent_allow_run_command',
        'true'::jsonb,
        'Whether the agent can call the run_command tool.'
    ),
    (
        'global',
        NULL,
        'agent_allow_write_files',
        'true'::jsonb,
        'Whether the agent can call write and replace file tools.'
    ),
    (
        'global',
        NULL,
        'agent_system_prompt',
        '"You are Knight, an autonomous software engineering agent. Work iteratively: inspect the repository, read files before editing, prefer targeted edits over broad rewrites, run commands when needed, and stop once the task is complete. Use the available tools to list files, read files, write files, replace text in files, inspect git status/diff, and run safe shell commands."'::jsonb,
        'System prompt used by the coding agent.'
    )
ON CONFLICT (scope, key, repository) DO NOTHING;
