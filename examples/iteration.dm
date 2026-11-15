matrix "bounded-iteration" {
    input rows
    budget steps 100
    foreach row in $rows limit 4 {
        let message = object(["position", $index], ["value", $row])
        wait 1s
        require approval
    }
    print "Reviewed iterations finished"
}
