# START HERE: no AI, computer commands, or external services.
# Review & Save the exact source, approve/save it, then explicitly Run.
# Opening/importing source grants no authority and starts nothing.
matrix "checkpoint" {
    description "A durable wait and native checkpoint record"
    version "1.2"
    budget steps 20
    failure stop

    # A function has explicit parameters, immutable locals and bounded expansion.
    function checkpoint_record {
        param state
        let record = object(["state", $state], ["wait_seconds", 60])
    }
    step begin { print "Checkpoint started" }

    # The server retains this deadline; no terminal process needs to sleep.
    # Worker pickup is periodic, so this is not an exact real-time timer.
    wait 60s
    call checkpoint_record { with state = "resumed" }
    save outputs as checkpoint
    if $checkpoint.state == "resumed" {
        print "Checkpoint completed; inspect the retained native JSON record."
    } else {
        print "Unexpected checkpoint state; inspect the recorded evidence."
    }
    # This has no trigger. Adding one edits the same source and requires review.
    # Workflow version is author metadata, not a language version selector.
}
