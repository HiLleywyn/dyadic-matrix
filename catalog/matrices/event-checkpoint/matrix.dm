# An authenticated producer delivers this event; its name alone subscribes to nothing.
# No AI, shell, message sending or external service is invoked.
matrix "event-checkpoint" {
    description "Retain and classify an explicitly delivered event"
    version "1.2"
    budget steps 20
    failure stop
    input event
    trigger { event "manual.check" }

    # Event payloads are data. Optional properties have explicit fallbacks.
    let event_record = object(["source", get($event, "source", "unspecified")], ["severity", get($event, "severity", "information")])
    if $event_record.severity == "critical" {
        print "A producer marked this event critical; inspect its source and retained payload."
        require approval
    } else {
        print "Event recorded without external effects. Inspect event_record and the original inputs."
    }
    # Review/save with Enable Automatic Runs before admitting future events:
    # dyadic matrix emit manual.check --id check-001 --body '{"source":"manual","severity":"information"}' --yes
    # The same event ID and payload deduplicate within the retention window.
    # In place of an event, a numeric weekday cron is:
    # trigger { cron "0 8 * * 1-5" zone "America/Chicago" }
    # No automatic trigger is enabled merely by importing this template.
}
