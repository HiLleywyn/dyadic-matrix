-- Durable Matrix cursors. Effects, permissions and money retain their existing owners.
CREATE TABLE workspace_matrices (
 id uuid PRIMARY KEY, user_id bigint NOT NULL,
 name text NOT NULL CHECK(length(name) BETWEEN 1 AND 64), revision integer NOT NULL DEFAULT 1,
 source text NOT NULL CHECK(octet_length(source)<=262144), source_sha256 text NOT NULL,
 graph jsonb NOT NULL, bindings jsonb NOT NULL, review_sha256 text NOT NULL,
 enabled boolean NOT NULL DEFAULT false, triggers jsonb NOT NULL DEFAULT '[]', next_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,name), UNIQUE(id,user_id)
);
CREATE INDEX workspace_matrices_due ON workspace_matrices(next_at) WHERE enabled;
CREATE TABLE workspace_matrix_runs (
 id uuid PRIMARY KEY, user_id bigint NOT NULL,
 matrix_id uuid NOT NULL, parent_id uuid, depth integer NOT NULL DEFAULT 0 CHECK(depth BETWEEN 0 AND 8),
 source text NOT NULL, source_sha256 text NOT NULL, review_sha256 text NOT NULL,
 graph jsonb NOT NULL, bindings jsonb NOT NULL, input jsonb NOT NULL DEFAULT '{}',
 state text NOT NULL DEFAULT 'running' CHECK(state IN ('running','paused','attention','completed','failed','cancelled')),
 cause text NOT NULL, request_key text NOT NULL, request_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(matrix_id,user_id) REFERENCES workspace_matrices(id,user_id) ON DELETE CASCADE,
 UNIQUE(user_id,request_key), UNIQUE(id,user_id),
 FOREIGN KEY(parent_id,user_id) REFERENCES workspace_matrix_runs(id,user_id)
);
CREATE INDEX workspace_matrix_runs_active ON workspace_matrix_runs(updated_at) WHERE state='running';
CREATE TABLE workspace_matrix_steps (
 run_id uuid NOT NULL, user_id bigint NOT NULL, key text NOT NULL, spec jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','dispatching','waiting','approval','completed','skipped','failed','unknown')),
 request_id uuid NOT NULL UNIQUE, receipt jsonb NOT NULL DEFAULT '{}', dispatch_input jsonb, output jsonb,
 wake_at timestamptz, lease_until timestamptz, approved_sha256 text,
 started_at timestamptz, finished_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(run_id,key), FOREIGN KEY(run_id,user_id) REFERENCES workspace_matrix_runs(id,user_id) ON DELETE CASCADE
);
CREATE INDEX workspace_matrix_steps_wait ON workspace_matrix_steps(wake_at) WHERE state='waiting';
CREATE INDEX workspace_matrix_steps_job ON workspace_matrix_steps((receipt->>'job_id')) WHERE receipt ? 'job_id';
CREATE TABLE workspace_matrix_events (
 id bigserial PRIMARY KEY, run_id uuid NOT NULL, user_id bigint NOT NULL, kind text NOT NULL,
 step text, detail jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(run_id,user_id) REFERENCES workspace_matrix_runs(id,user_id) ON DELETE CASCADE
);
CREATE INDEX workspace_matrix_events_run ON workspace_matrix_events(run_id,id);
CREATE TABLE workspace_matrix_triggers (
 user_id bigint NOT NULL,
 event_id text NOT NULL CHECK(length(event_id) BETWEEN 1 AND 200), name text NOT NULL,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,event_id)
);
CREATE TABLE workspace_matrix_invocations (
 user_id bigint NOT NULL, matrix_id uuid NOT NULL, request_key text NOT NULL,
 review_sha256 text NOT NULL, payload jsonb NOT NULL DEFAULT '{}', cause text NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','delivered','blocked')),
 created_at timestamptz NOT NULL DEFAULT now(), checked_at timestamptz NOT NULL DEFAULT now(), reason text NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,request_key), FOREIGN KEY(matrix_id,user_id) REFERENCES workspace_matrices(id,user_id) ON DELETE CASCADE
);
