"""Inspect Matrix source and run explicitly reviewed local workflows."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from . import __version__
from .errors import Invalid
from .language import compile_source
from .values import compile_expression, evaluate


def main(argv=None):
    # Native Windows executables can otherwise inherit a legacy console code
    # page even when redirected. JSON/data output has one portable encoding.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='dm', description=__doc__)
    parser.add_argument('--version', action='version', version='dm ' + __version__)
    commands = parser.add_subparsers(dest='command', required=True)
    validate = commands.add_parser('validate', help='Compile exact source without executing it')
    validate.add_argument('source', type=Path)
    validate.add_argument('--json', action='store_true')
    expression = commands.add_parser('expr', help='Evaluate bounded pure JSON data without tools or models')
    expression.add_argument('expression')
    expression.add_argument('--input-file', type=Path)
    review = commands.add_parser('review', help='Resolve a local policy and show the exact source/plan review')
    review.add_argument('source', type=Path);review.add_argument('--policy', type=Path, required=True)
    review.add_argument('--json', action='store_true')
    initialize = commands.add_parser('init-db', help='Initialize the engine schema in your dedicated PostgreSQL database')
    initialize.add_argument('--yes', action='store_true', required=True)
    install = commands.add_parser('install', help='Install exact reviewed source without starting it')
    install.add_argument('source', type=Path);install.add_argument('--review', required=True)
    install.add_argument('--revision', type=int);install.add_argument('--enable', action='store_true')
    run = commands.add_parser('run', help='Start an installed, currently reviewed local workflow')
    run.add_argument('matrix');run.add_argument('--input-file', type=Path)
    run.add_argument('--request-key', required=True);run.add_argument('--review', required=True)
    inspect = commands.add_parser('inspect', help='Inspect retained run steps, receipts, events and approval subjects')
    inspect.add_argument('run');inspect.add_argument('--after', type=int, default=0)
    approve = commands.add_parser('approve', help='Approve an exact waiting subject; leaves the run paused')
    approve.add_argument('run');approve.add_argument('step');approve.add_argument('--review', required=True)
    worker = commands.add_parser('worker', help='Advance durable work; foreground observation does not own stored cursors')
    worker.add_argument('--once', action='store_true')
    for name in ('pause', 'resume', 'cancel', 'reconcile'):
        command = commands.add_parser(name);command.add_argument('run')
    for command in (install, run, approve, *(commands.choices[n] for n in ('pause', 'resume', 'cancel', 'reconcile'))):
        command.add_argument('--yes', action='store_true', required=True)
    for command in (install, run, inspect, approve, worker, *(commands.choices[n] for n in ('pause', 'resume', 'cancel', 'reconcile'))):
        command.add_argument('--policy', type=Path, required=True)
        command.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'expr':
            values = json.loads(args.input_file.read_text(encoding='utf-8')) if args.input_file else {}
            if not isinstance(values, dict): raise Invalid('Expression input must be a JSON object.')
            print(json.dumps(evaluate(compile_expression(args.expression), values), ensure_ascii=False, allow_nan=False))
        elif args.command == 'validate':
            graph = compile_source(args.source.read_bytes().decode('utf-8'))
            if args.json: print(json.dumps(graph, ensure_ascii=False, allow_nan=False, indent=2))
            else:
                print(f"{graph['name']}: {len(graph['steps'])} steps, {len(graph['triggers'])} triggers")
                print('Source SHA-256: ' + graph['source_sha256'])
                print('Plan SHA-256:   ' + graph['plan_sha256'])
                print('Source validation only. No effects dispatched.')
        elif args.command == 'review':
            from .local import LocalHost
            result = LocalHost(None, args.policy).review(args.source.read_bytes().decode('utf-8'))
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            asyncio.run(execution(args))
        return 0
    except Invalid as exc:
        print('dm: ' + str(exc), file=sys.stderr);return 2
    except (OSError, UnicodeError, ValueError):
        # Do not echo arbitrary source/data, connection strings or file content.
        print('dm: source, input or expression is invalid; check syntax, types and documented bounds.', file=sys.stderr)
        return 2
    except KeyboardInterrupt: return 130
    except Exception:
        print('dm: operation failed. Inspect retained state before retrying an external effect.', file=sys.stderr);return 1


async def execution(args):
    from .durable import decoded, digest
    from .local import LocalHost
    from .postgres import Database
    dsn = os.environ.get('DM_DATABASE_URL')
    if not dsn: raise Invalid('Set DM_DATABASE_URL to your dedicated local PostgreSQL database. Credentials never belong in source or CLI arguments.')
    db = await Database.connect(dsn)
    try:
        if args.command == 'init-db':
            async with db.atomic() as conn:
                await conn.execute(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
            print('Initialized dm schema.');return
        host = LocalHost(db, args.policy);store = host.store
        if args.command == 'install':
            source = args.source.read_bytes().decode('utf-8');review = host.review(source)
            if args.review != review['review_sha256']: raise Invalid('The source, plan or policy changed. Review this exact source again.')
            result = await store.register(host.actor, source, review['bindings'], args.review, expected_revision=args.revision, enabled=args.enable)
        elif args.command == 'run':
            definition = await store.definition(host.actor, args.matrix);host.verify(definition)
            if args.review != definition['review_sha256']: raise Invalid('Review the current installed source and local policy before starting it.')
            values = json.loads(args.input_file.read_text(encoding='utf-8')) if args.input_file else {}
            run = await store.start(host.actor, args.matrix, args.request_key, inputs=values)
            result = await store.inspect(host.actor, run['id'])
        elif args.command == 'inspect':
            result = await store.inspect(host.actor, args.run, args.after)
            result['approvals'] = {s['key']: digest({'run_id': str(result['run']['id']), 'step': s['key'], 'source_sha256': result['run']['source_sha256'], 'output': decoded(s['output'])}) for s in result['steps'] if s['state'] == 'approval'}
        elif args.command == 'approve': result = await store.approve_step(host.actor, args.run, args.step, args.review)
        elif args.command in ('pause', 'resume', 'cancel'): result = await store.control(host.actor, args.run, args.command)
        elif args.command == 'reconcile': result = await store.reconcile(host.actor, args.run, host)
        elif args.command == 'worker':
            while True:
                await host.tick()
                if args.once: break
                await asyncio.sleep(1)
            result = {'advanced': True}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally: await db.close()
