# Pair your computers, then replace computer-a and computer-b with exact names/IDs.
# Commands are reviewed literals; input/model data cannot manufacture targets.
# This workflow makes no model calls and performs no automatic repair.
matrix "fleet-diagnostics" {
    description "Collect paired computer identities and index their observed receipts"
    version "1.2"
    budget steps 30
    failure stop
    step collect {
        parallel {
            on "computer-a" {
                # Offline admission may retry; nonzero/unknown effects never replay blindly.
                retry 2 backoff 2s
                run "hostname" }
            on "computer-b" {
                # Offline admission may retry; nonzero/unknown effects never replay blindly.
                retry 2 backoff 2s
                run "hostname" }
        }
        save outputs as diagnostics
    }
    # Aggregate actual receipt fields without an AI call. Unknown fields remain
    # explicit, and a successful command does not verify the host's health.
    let computers = map($diagnostics, object(["computer", get($item, "computer", "unknown")], ["exit_code", get($item, "exit_code", null)], ["truncated", get($item, "output_truncated", false)]))
    let incomplete = filter($computers, $item.truncated == true)
    if length($incomplete) > 0 {
        print "Some identity output was truncated; inspect those original receipts."
    } else {
        print "Identity collection finished. Inspect computers and the original command receipts."
    }
    # Failed/disconnected effects retain failure/unknown states; no blind replay.
    # Optional explicit cadence: trigger { interval 1h }
}
