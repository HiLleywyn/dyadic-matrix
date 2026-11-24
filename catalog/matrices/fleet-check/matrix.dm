# Requires: paired Linux and Windows hosts, systemd, PowerShell, and Docker access on container-host.
# Configure: linux-server, windows-pc and container-host plus diagnostics/analyst profiles.
# The schedule is UTC and remains inactive until the reviewed Matrix is explicitly enabled.
# A stopped Windows service is not automatically a failure; reported counters are point-in-time observations.
# Produces: host inventory, service and capacity findings, prioritized follow-ups and a reviewer handoff.

matrix "fleet-check" {
    description "Gather Linux, Windows and Docker diagnostics in parallel and produce a host-specific health and capacity review."
    version "1.2"
    budget steps 60
    failure stop

    trigger {
        schedule "08:00" every "weekday" zone "UTC"
    }

    # Native receipt indexing does not ask a model to interpret exit codes.
    # Parameters are explicit; this function cannot capture ambient variables.
    function summarize_collection {
        param rows
        let index = map($rows, object(["source", $item.source], ["exit_code", get($item.record, "exit_code", null)], ["truncated", get($item.record, "output_truncated", false)]))
    }

    step collect {
        parallel {
            step linux {
                profile "diagnostics"
                on "linux-server" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    run "uname -srmo"
                    save outputs as linux_identity
                    run "df -h -x tmpfs -x devtmpfs"
                    save outputs as linux_disk
                    run "systemctl --failed --no-pager --plain"
                    save outputs as linux_services
                }
            }
            step windows {
                profile "diagnostics"
                on "windows-pc" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    run "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,LastBootUpTime,FreePhysicalMemory,TotalVisibleMemorySize | ConvertTo-Json -Compress"
                    save outputs as windows_os
                    run "Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" | Select-Object DeviceID,Size,FreeSpace | ConvertTo-Json -Compress"
                    save outputs as windows_disk
                    run "Get-CimInstance Win32_Service -Filter \"StartMode='Auto' AND State<>'Running'\" | Select-Object -First 30 Name,State,StartMode | ConvertTo-Json -Compress"
                    save outputs as windows_services
                }
            }
            step containers {
                profile "diagnostics"
                on "container-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    run "docker ps --all --last 100 --format \"{{json .}}\""
                    save outputs as container_state
                    run "docker stats --no-stream --format \"{{json .}}\" api worker postgres"
                    save outputs as container_usage
                    run "docker system df"
                    save outputs as docker_disk
                }
            }
        }
    }

    # Keep the original receipts. This derived index records only observed
    # command state; exit code zero is not a claim that the content is correct.
    let collector_records = [object(["source", "linux_identity"], ["record", $linux_identity]), object(["source", "linux_disk"], ["record", $linux_disk]), object(["source", "linux_services"], ["record", $linux_services]), object(["source", "windows_os"], ["record", $windows_os]), object(["source", "windows_disk"], ["record", $windows_disk]), object(["source", "windows_services"], ["record", $windows_services]), object(["source", "container_state"], ["record", $container_state]), object(["source", "container_usage"], ["record", $container_usage]), object(["source", "docker_disk"], ["record", $docker_disk])]
    call summarize_collection { with rows = $collector_records }
    save outputs as collector_index
    let collector_truncated = filter($collector_index, $item.truncated == true)
    if length($collector_truncated) > 0 {
        print "Some retained command output was truncated; include those evidence gaps in review."
    } else {
        print "No collector reported truncation; content still requires source-based review."
    }


    step inventory {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Use $linux_identity, $linux_disk, $linux_services, $windows_os, $windows_disk, $windows_services,
            $container_state, $container_usage and $docker_disk to build a host-by-host inventory.
            Keep host identity, operating-system units and collection scope attached to each observation.
            Distinguish unavailable hosts and failed collectors from an empty or healthy result.
            Do not equate stopped services, exited jobs or high memory allocation with a verified incident.
        }
        save response as inventory
    }

    step findings {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Review $inventory for service failures and storage or memory pressure.
            State the observation, source, operational implication and next bounded check for each finding.
            Separate Docker-reported reclaimable bytes from space that is safe to delete.
            Do not prune, remove images or volumes, restart containers, kill processes or alter services.
            Preserve uncertain state and note where trends require a second collection at a known time.
        }
        save response as findings
    }

    step report {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Draft an operations handoff from $inventory and $findings.
            Give a concise summary followed by a target-specific action queue with dependencies and approval needs.
            Include healthy observations as context without claiming comprehensive coverage.
            The next action is human review; no remediation or deployment has run in this Matrix.
        }
        save response as fleet_report
    }

    step review {
        require approval
        print "Review the saved report and original evidence in this run before taking action."
    }
}
