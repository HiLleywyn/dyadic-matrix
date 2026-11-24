# Requires Runner 2.10.0+ and Python 3 on the selected computer.
# Replace computer-a and python3 with the exact paired target/program before review.
# Manual input is JSON data. No value is interpolated into shell code.
matrix "structured-command" {
    description "Send bounded JSON data to a fixed program and inspect its retained outcome"
    version "1.2"
    budget steps 20
    input payload
    let serialized = text($payload)
    step observe {
        failure continue
        retry 2 backoff 2s
        on "computer-a" {
            exec "python3" {
                args ["-c", "import json,sys; print(json.dumps(json.loads(sys.argv[2]),ensure_ascii=False))", "--", $serialized]
            }
        }
        save outcome as observed
    }
    if $observed.state == "failed" {
        print "The process failed. Inspect the original receipt; no repair was attempted."
    } else {
        print "Argument data was processed. Inspect output; completion alone is not independent verification."
    }
    # Only an adapter-established safe pre-effect failure qualifies for retry.
    # A nonzero exit can already have effects and is not automatically replayed.
    # Unknown outcomes block this branch until reconciliation and explicit resume.
}
