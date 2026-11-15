matrix "local-checkpoint" {
    description "A local command followed by exact review"
    on "local" { run "echo local-checkpoint" }
    save outputs as observed
    wait 1s
    require approval
    print "The local checkpoint was reviewed"
}
