matrix "scheduled-checkpoint" {
    trigger {
        interval 6h
        cron "0 8 * * 1-5" zone "America/Chicago"
    }
    print "The durable scheduler admitted a checkpoint"
}
