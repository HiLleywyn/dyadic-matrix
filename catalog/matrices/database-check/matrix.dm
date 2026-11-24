# Requires: PostgreSQL 14+ psql and a postgres-observer service using a genuinely read-only monitoring role.
# Configure: database-host and application-host, postgres-observer in pg_service.conf, and diagnostics/analyst profiles.
# SQL transactions are read only with local five-second statement and one-second lock timeouts.
# Application diagnostics assume systemd service app and deliberately omit request bodies and full query text.
# Produces: activity and capacity ledger, competing explanations, and a ranked read-only investigation plan.

matrix "database-check" {
    description "Inspect bounded read-only PostgreSQL activity and host pressure, then build an evidence-based investigation plan."
    version "1.2"
    budget steps 60
    failure stop

    # Native receipt indexing does not ask a model to interpret exit codes.
    # Parameters are explicit; this function cannot capture ambient variables.
    function summarize_collection {
        param rows
        let index = map($rows, object(["source", $item.source], ["exit_code", get($item.record, "exit_code", null)], ["truncated", get($item.record, "output_truncated", false)]))
    }

    step collect {
        parallel {
            step activity {
                profile "diagnostics"
                on "database-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    run "psql -X 'service=postgres-observer' -v ON_ERROR_STOP=1 -P pager=off -c \"BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT datname,state,wait_event_type,wait_event,count(*) AS sessions FROM pg_stat_activity GROUP BY 1,2,3,4 ORDER BY sessions DESC LIMIT 30; COMMIT;\""
                    save outputs as sessions
                    run "psql -X 'service=postgres-observer' -v ON_ERROR_STOP=1 -P pager=off -c \"BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT datname,numbackends,xact_commit,xact_rollback,deadlocks,temp_bytes,stats_reset FROM pg_stat_database WHERE datname IS NOT NULL ORDER BY numbackends DESC LIMIT 20; COMMIT;\""
                    save outputs as database_stats
                }
            }
            step relations {
                profile "diagnostics"
                on "database-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    run "psql -X 'service=postgres-observer' -v ON_ERROR_STOP=1 -P pager=off -c \"BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT schemaname,relname,n_live_tup,n_dead_tup,last_autovacuum,last_autoanalyze FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 20; COMMIT;\""
                    save outputs as table_stats
                }
            }
            step host_pressure {
                profile "diagnostics"
                on "application-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    run "free -m"
                    save outputs as memory
                    run "df -h -x tmpfs -x devtmpfs"
                    save outputs as disk
                    run "systemctl show app --property=ActiveState,SubState,Result,NRestarts,ActiveEnterTimestamp"
                    save outputs as app_state
                }
            }
        }
    }

    # Keep the original receipts. This derived index records only observed
    # command state; exit code zero is not a claim that the content is correct.
    let collector_records = [object(["source", "sessions"], ["record", $sessions]), object(["source", "database_stats"], ["record", $database_stats]), object(["source", "table_stats"], ["record", $table_stats]), object(["source", "memory"], ["record", $memory]), object(["source", "disk"], ["record", $disk]), object(["source", "app_state"], ["record", $app_state])]
    call summarize_collection { with rows = $collector_records }
    save outputs as collector_index
    let collector_truncated = filter($collector_index, $item.truncated == true)
    if length($collector_truncated) > 0 {
        print "Some retained command output was truncated; include those evidence gaps in review."
    } else {
        print "No collector reported truncation; content still requires source-based review."
    }


    step measurements {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Use $sessions, $database_stats, $table_stats, $memory, $disk and $app_state.
            Build a measurement table with target, measurement, units and source variable.
            Cumulative counters are not rates. Explain that their reset timestamps bound their interpretation.
            Do not infer query latency from session count, container memory, dead tuples or disk occupancy alone.
            Highlight unavailable monitoring permissions and absent timestamps instead of silently filling them in.
            Do not expose credentials, query parameters, customer data or request bodies.
        }
        save response as measurements
    }

    step hypotheses {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Use $measurements to compare at least three plausible explanations for the reported slowdown.
            For each explanation list supporting evidence, contradicting evidence and the missing measurement.
            Distinguish locks, connection pressure, I/O, statistics and application restarts where the evidence allows.
            Give read-only follow-up queries with limits and timeouts; do not execute those suggestions.
            Do not recommend killing sessions, vacuuming, adding indexes or changing configuration as an automatic action.
        }
        save response as investigation
    }

    step handoff {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Prepare the DBA handoff from $measurements and $investigation.
            Include immediate observations, the smallest next measurement and an escalation threshold that needs owner review.
            List unresolved uncertainty and the privileges required for proposed follow-up checks.
            Separate an investigation plan from a maintenance approval. No database changes were authorized by this report.
        }
        save response as database_report
    }

    step review {
        require approval
        print "Review the saved report and original evidence in this run before taking action."
    }
}
