"""Local source inspection. Compilation is inert and requires no Dyadic account."""
import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .errors import Invalid
from .language import compile_source
from .values import compile_expression, evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dm', description=__doc__)
    parser.add_argument('--version', action='version', version='dm ' + __version__)
    commands = parser.add_subparsers(dest='command', required=True)
    validate = commands.add_parser('validate', help='Compile exact source without executing it')
    validate.add_argument('source', type=Path)
    validate.add_argument('--json', action='store_true')
    expression = commands.add_parser('expr', help='Evaluate bounded pure JSON data without tools or models')
    expression.add_argument('expression')
    expression.add_argument('--input-file', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'expr':
            values = json.loads(args.input_file.read_text(encoding='utf-8')) if args.input_file else {}
            if not isinstance(values, dict): raise Invalid('Expression input must be a JSON object.')
            print(json.dumps(evaluate(compile_expression(args.expression), values), ensure_ascii=False, allow_nan=False))
        else:
            graph = compile_source(args.source.read_bytes().decode('utf-8'))
            if args.json: print(json.dumps(graph, ensure_ascii=False, allow_nan=False, indent=2))
            else:
                print(f"{graph['name']}: {len(graph['steps'])} steps, {len(graph['triggers'])} triggers")
                print('Source SHA-256: ' + graph['source_sha256'])
                print('Plan SHA-256:   ' + graph['plan_sha256'])
                print('Source validation only. No effects dispatched.')
        return 0
    except (Invalid, OSError, UnicodeError, ValueError):
        # Do not echo arbitrary source/data, connection strings or file content.
        print('dm: source, input or expression is invalid; check syntax, types and documented bounds.', file=sys.stderr)
        return 2
