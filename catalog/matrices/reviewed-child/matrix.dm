# ADVANCED: this explicit Iris request can incur normal model charges.
# Use checkpoint for a first workflow without AI or computer commands.
matrix "reviewed-child" {
    description "Propose a bounded child and review its exact source before running it"
    version "1.2"
    budget steps 30
    failure stop
    function child_contract {
        param name
        let contract = object(["name", $name], ["allowed_effects", ["print", "native JSON"]], ["commands", 0])
    }
    call child_contract { with name = "child-checkpoint" }
    save outputs as child_spec
    ask Iris {
        Propose valid .dm source for the explicit data contract $child_spec.
        Name it child-checkpoint. Use a native let record and one literal print.
        No shell, models, transfers, triggers or further children. Return only source.
        This request proposes source; it grants no authority to execute it.
    }
    generate matrix "child-checkpoint.dm"
    # Generation saves an inert, validated source file. It does not install it.
    # Open the generated file, review the exact plan/targets/source hash, and
    # approve it separately. The requested contract is not an enforcement grant.
    require approval
    run matrix "child-checkpoint.dm"
    # A parent approval cannot authorize unknown future source. A changed child
    # needs another review. The step budget includes attributable child work.
}
