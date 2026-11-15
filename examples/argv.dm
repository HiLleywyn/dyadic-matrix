# Requires an installed python3 executable. On Windows, choose its actual name
# or full path in BOTH this source and argv-policy.json before fresh review.
# The native dm package is not a general-purpose Python interpreter.
matrix "literal-program-data-args" {
    input message
    budget steps 10
    on "local" {
        exec "python3" {
            args ["-c", "import json,sys; print(json.dumps(sys.argv[1:]))", "--", $message]
        }
    }
    save outcome as observed
}
