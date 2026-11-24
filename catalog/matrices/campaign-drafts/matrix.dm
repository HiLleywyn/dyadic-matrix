# Requires: campaign-brief.md, product-evidence.json and brand-notes.md, each UTF-8 and at most 128 KiB.
# Configure: creative-host, /srv/dyadic/campaign-inputs and diagnostics/writer/analyst profiles.
# The product evidence should include approved claims, limitations, supporting references and expiry dates where relevant.
# Produces: message architecture, landing-page/email/social drafts, claims audit and a publication review checklist.
# No image generation, mailing-list access, email sending, ad spending or publication is performed.

matrix "campaign-drafts" {
    description "Turn an approved brief and product evidence into consistent draft assets, then audit claims and prepare a review package."
    version "1.2"
    budget steps 60
    failure stop

    # Native receipt indexing does not ask a model to interpret exit codes.
    # Parameters are explicit; this function cannot capture ambient variables.
    function summarize_collection {
        param rows
        let index = map($rows, object(["source", $item.source], ["exit_code", get($item.record, "exit_code", null)], ["truncated", get($item.record, "output_truncated", false)]))
    }

    step collect {
        parallel {
            step brief {
                profile "diagnostics"
                on "creative-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    cwd "/srv/dyadic/campaign-inputs"
                    run "python3 -c 'import pathlib; p=pathlib.Path(\"campaign-brief.md\"); assert p.stat().st_size <= 131072; print(p.read_text())'"
                    save outputs as brief
                }
            }
            step evidence {
                profile "diagnostics"
                on "creative-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    cwd "/srv/dyadic/campaign-inputs"
                    run "python3 -c 'import json,pathlib; p=pathlib.Path(\"product-evidence.json\"); assert p.stat().st_size <= 131072; print(json.dumps(json.loads(p.read_text()),indent=2))'"
                    save outputs as product_evidence
                }
            }
            step brand {
                profile "diagnostics"
                on "creative-host" {
                    # Offline admission may retry; nonzero/unknown effects never replay blindly.
                    retry 2 backoff 2s
                    cwd "/srv/dyadic/campaign-inputs"
                    run "python3 -c 'import pathlib; p=pathlib.Path(\"brand-notes.md\"); assert p.stat().st_size <= 131072; print(p.read_text())'"
                    save outputs as brand_notes
                }
            }
        }
    }

    # Keep the original receipts. This derived index records only observed
    # command state; exit code zero is not a claim that the content is correct.
    let collector_records = [object(["source", "brief"], ["record", $brief]), object(["source", "product_evidence"], ["record", $product_evidence]), object(["source", "brand_notes"], ["record", $brand_notes])]
    call summarize_collection { with rows = $collector_records }
    save outputs as collector_index
    let collector_truncated = filter($collector_index, $item.truncated == true)
    if length($collector_truncated) > 0 {
        print "Some retained command output was truncated; include those evidence gaps in review."
    } else {
        print "No collector reported truncation; content still requires source-based review."
    }


    step message_architecture {
        gateway "dyadic"
        profile "writer"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Use $brief, $product_evidence and $brand_notes to establish the campaign message architecture.
            Identify audience, concrete problem, supported value proposition, tone and intended next action.
            List claims that have approved evidence and claims requiring clarification.
            Preserve product limitations and any prohibited wording. Do not invent pricing, testimonials or results.
        }
        save response as messages
    }

    step draft_assets {
        gateway "dyadic"
        profile "writer"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Use $messages, $brief and $brand_notes to draft a landing page, one email and three distinct social posts.
            Keep the value proposition and product names consistent while adapting length and purpose to each channel.
            Include email subject and preview text, a single clear next action and factual links from the approved brief.
            Label placeholders and missing URLs. Keep every asset an unsent, unpublished draft.
            Do not use unsupported superiority claims, invented customer quotes or fabricated metrics.
        }
        save response as assets
    }

    step claims_audit {
        gateway "dyadic"
        profile "analyst"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Audit $assets against $product_evidence, $brief and $brand_notes.
            Produce a claim-by-claim table with draft location, evidence reference and required revision.
            Identify missing qualification, misleading implication, unavailable functionality and inconsistent terminology.
            Separate editorial suggestions from evidence failures. Do not silently invent substitute facts.
        }
        save response as claims_audit
    }

    step review_package {
        gateway "dyadic"
        profile "writer"
        ask Iris {
            Use $collector_index for observed command outcomes and truncation flags. Preserve evidence gaps.
            Use $assets and $claims_audit to prepare the final review package.
            Provide the corrected draft assets plus a change log tracing evidence-related corrections.
            List unresolved claims, missing links, audience checks and the approvals needed before publication.
            No email has been sent and no campaign has been published by this workflow.
        }
        save response as campaign_package
    }

    step review {
        require approval
        print "Review the saved report and original evidence in this run before taking action."
    }
}
