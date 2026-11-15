matrix "native-data" {
    description "Filter observed JSON and review its deterministic total"
    input readings
    function total {
        param rows
        let counts = map($rows, $item.count)
        let result = sum($counts)
    }
    let selected = filter($readings, $item.ok == true)
    call total { with rows = $selected }
    save outputs as count
    if $count > 0 {
        print "Readings are ready for review"
    } else {
        print "No positive readings"
    }
    require approval
}
