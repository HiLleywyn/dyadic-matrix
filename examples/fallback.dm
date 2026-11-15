matrix "known-failure-fallback" {
    description "Branch on a retained known failure; unknown outcomes still stop"
    budget steps 20
    step primary {
        failure continue
        on "local" { run "exit 7" }
        save outcome as observed
    }
    if $observed.state == "failed" {
        # A fallback is another explicit, reviewed effect, not a hidden retry.
        on "local" { run "echo fallback" }
        save outputs as fallback
    } else {
        print "The primary command succeeded; no fallback was needed."
    }
}
