"""Dyadic Matrix source grammar. Parsing is inert; source remains the lossless owner.

The bounded tree is a derived execution index, not an alternative authored format.
No Python, shell interpolation or host template code is evaluated. Expressions
compile to the bounded pure-data IR owned by matrix_values.
"""
from __future__ import annotations

import hashlib
import json
import re
from .errors import Invalid

MAX_SOURCE = 256 * 1024
MAX_BLOCKS = 256
MAX_DEPTH = 12
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_-]{0,63}$')
TOKEN = re.compile(r'(?P<space>[ \t\r]+)|(?P<comment>//[^\n]*|\#[^\n]*)|(?P<line>\n)|'
                   r'(?P<string>"(?:[^"\\]|\\.)*")|(?P<symbol>==|!=|[{}])|(?P<word>[^\s{}"]+)')


def parse(source: str) -> dict:
    try: size = len(source.encode('utf-8')) if isinstance(source, str) else MAX_SOURCE + 1
    except UnicodeError: raise Invalid('Matrix source must be valid UTF-8 text.') from None
    if size > MAX_SOURCE or '\0' in source:
        raise Invalid('A Matrix must be UTF-8 text of at most 256 KiB without NUL characters.')
    tokens = []
    line, offset = 1, 0
    for match in TOKEN.finditer(source):
        if match.start() != offset:
            raise Invalid(f'Invalid Matrix syntax on line {line}.')
        offset = match.end()
        kind, text = match.lastgroup, match.group()
        if kind not in ('space', 'comment'):
            tokens.append((kind, text, line, match.start(), match.end()))
        line += text.count('\n')
    if offset != len(source):
        raise Invalid(f'Invalid Matrix syntax on line {line}.')
    index, count = 0, 0

    def block(depth=0):
        nonlocal index, count
        if depth > MAX_DEPTH:
            raise Invalid('Matrix blocks are nested too deeply.')
        nodes = []
        while index < len(tokens):
            kind, text, at, _, _ = tokens[index]
            if kind == 'line':
                index += 1
                continue
            if text == '}':
                if not depth:
                    raise Invalid(f'Unexpected closing block on line {at}.')
                index += 1
                return nodes
            node_start = tokens[index][3]
            words = []
            while index < len(tokens) and tokens[index][0] != 'line' and tokens[index][1] not in ('{', '}'):
                kind, word, *_ = tokens[index]
                try:
                    words.append(json.loads(word) if kind == 'string' else word)
                except ValueError:
                    raise Invalid(f'Invalid quoted string on line {at}.') from None
                index += 1
            if not words:
                raise Invalid(f'Expected a Matrix statement on line {at}.')
            count += 1
            if count > MAX_BLOCKS:
                raise Invalid('A Matrix has at most 256 statements.')
            node = {'words': words, 'line': at}
            header_end = tokens[index][3] if index < len(tokens) and tokens[index][1] == '{' else tokens[index - 1][4]
            if index < len(tokens) and tokens[index][1] == '{':
                node['body_start'] = tokens[index][4]
                if words == ['ask', 'Iris']:
                    start, balance = tokens[index][4], 1
                    index += 1
                    while index < len(tokens) and balance:
                        if tokens[index][1] == '{': balance += 1
                        if tokens[index][1] == '}': balance -= 1
                        if balance: index += 1
                    if balance:
                        raise Invalid(f'Close the Iris prompt block on line {at}.')
                    node['prompt'] = source[start:tokens[index][3]].strip()
                    node['body_end'] = tokens[index][3]
                    index += 1
                else:
                    index += 1
                    node['body'] = block(depth + 1)
                    node['body_end'] = tokens[index - 1][3]
            node['range'] = {'start': node_start, 'header_end': header_end, 'end': tokens[index - 1][4]}
            nodes.append(node)
        if depth:
            raise Invalid('Close every Matrix block with }.')
        return nodes

    roots = block()
    if len(roots) != 1 or roots[0]['words'][:1] != ['matrix'] or len(roots[0]['words']) != 2 or 'body' not in roots[0]:
        raise Invalid('Use matrix "name" { ... } as the document root.')
    name = roots[0]['words'][1]
    if not NAME.fullmatch(name):
        raise Invalid('Use a Matrix name containing letters, numbers, underscores and hyphens.')
    return {'language': 'dyadic.matrix/1', 'name': name, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'body': roots[0]['body'], 'range_unit': 'unicode_codepoints', 'body_end': roots[0]['body_end']}


def compile_source(source: str) -> dict:
    """Produce a bounded, deterministic graph; unknown syntax is an error, never ignored."""
    tree = parse(source)
    from . import values as matrix_values
    steps, triggers, labels, variables = [], [], set(), set()
    inputs, variable_nodes, file_variables = [], {}, set()
    metadata, budgets = {}, {'steps': 60}
    functions, imports = {}, {}
    expansions, plan_bytes = 0, 0

    def fail(node, message):
        raise Invalid(f"Line {node['line']}: {message}")

    def emit(node, kind, after, scope, **detail):
        nonlocal plan_bytes
        if len(steps) >= budgets['steps']:
            fail(node, 'Matrix expanded steps exceed the reviewed step budget.')
        key = f'n{len(steps) + 1}'
        spec = {'key': key, 'kind': kind, 'after': list(after), 'line': node['line'], **scope, **detail}
        try: plan_bytes += len(json.dumps(spec, ensure_ascii=False).encode())
        except UnicodeError: fail(node, 'Matrix values must be valid UTF-8 text.')
        if plan_bytes > 400000: fail(node, 'The expanded Matrix plan exceeds its retained-size bound.')
        steps.append(spec)
        return [key]

    def compiled(node, text, aliases, local_only=False):
        try:
            result = matrix_values.compile_expression(text)
            if local_only and matrix_values.references(result) - aliases.keys():
                fail(node, 'Functions use explicit parameters and their own local values; ambient caller values are unavailable.')
            result = matrix_values.rename(result, aliases)
        except Invalid as exc: fail(node, str(exc))
        if matrix_values.references(result) - variables:
            fail(node, 'An expression must reference declared inputs or previously saved values.')
        return result

    def expression(node, prefix, aliases, local_only=False):
        header = source[node['range']['start']:node['range']['header_end']].strip()
        start = re.match(r'^let\s+\S+\s*=\s*' if prefix == 'let' else r'^if\s+', header)
        if not start: fail(node, 'Supply a complete expression.')
        return compiled(node, header[start.end():].strip(), aliases, local_only)

    def declare_function(node, prefix=''):
        w = node['words']
        if len(w) != 2 or not node.get('body') or not NAME.fullmatch(w[1]) or w[1].startswith('_matrix_') or prefix + w[1] in functions:
            fail(node, 'Declare unique source-local function names.')
        params, statements = [], []
        for child in node['body']:
            words = child['words']
            if words[:1] == ['param']:
                if len(words) != 2 or 'body' in child or statements or not NAME.fullmatch(words[1]) or words[1].startswith('_matrix_') or words[1] in params or len(params) >= 16:
                    fail(child, 'Declare up to sixteen unique parameters before function statements.')
                params.append(words[1])
            else: statements.append(child)
        if not statements: fail(node, 'A function needs executable statements.')
        identity = hashlib.sha256(source[node['range']['start']:node['range']['end']].encode()).hexdigest()
        functions[prefix + w[1]] = (params, statements, identity)

    def walk(nodes, after=(), scope=None, aliases=None, namespace='', calls=()):
        nonlocal expansions
        aliases = aliases if aliases is not None else {}
        scope = dict(scope or {})
        tail = list(after)
        previous_if = None
        for node in nodes:
            w, body = node['words'], node.get('body')
            op = w[0]
            alternate = previous_if if op == 'else' else None
            previous_if = None
            def local_name(name):
                if not NAME.fullmatch(name) or name.startswith('_matrix_'):
                    fail(node, 'Choose an identifier outside the reserved _matrix_ namespace.')
                return namespace + name
            if op in ('gateway', 'profile', 'cwd') and len(w) == 2 and body is None:
                scope[op] = w[1]
            elif op == 'step' and len(w) == 2 and body is not None:
                label = local_name(w[1])
                if label in labels:
                    fail(node, 'Step names must be unique identifiers.')
                labels.add(label)
                tail = walk(body, tail, {**scope, 'label': label}, aliases=aliases, namespace=namespace, calls=calls)
            elif op == 'parallel' and len(w) == 1 and body:
                if len(body) > 8: fail(node, 'A parallel block has at most eight branches.')
                tails = []
                for child in body:
                    if child['words'][0] not in ('on', 'step'):
                        fail(child, 'A parallel block contains on "computer" or step blocks.')
                    tails += walk([child], tail, scope, aliases=aliases, namespace=namespace, calls=calls)
                tail = tails
            elif op == 'on' and len(w) == 2 and body is not None:
                tail = walk(body, tail, {**scope, 'computer': w[1]}, aliases=aliases, namespace=namespace, calls=calls)
            elif op == 'call' and len(w) == 2 and body is not None:
                name = w[1]
                if name not in functions or name in calls or len(calls) >= 8:
                    fail(node, 'Call a declared source-local function without recursion, at most eight levels deep.')
                params, statements, identity = functions[name]
                arguments = {}
                for argument in body:
                    header = source[argument['range']['start']:argument['range']['header_end']].strip()
                    match = re.fullmatch(r'with\s+([A-Za-z_][\w-]*)\s*=\s*(.+)', header)
                    if not match or 'body' in argument or match[1] in arguments:
                        fail(argument, 'Supply each function parameter once with NAME = EXPRESSION.')
                    arguments[match[1]] = compiled(argument, match[2], aliases, bool(calls))
                if set(arguments) != set(params): fail(node, 'Supply exactly the declared function parameters.')
                expansions += 1
                prefix = f'_matrix_{expansions}_function_'
                inner = {**scope, 'calls': [*scope.get('calls', []), {'name': name, 'line': node['line'], 'source_sha256': identity}]}
                names = {}
                for param in params:
                    variable = prefix + param
                    tail = emit(node, 'value', tail, inner, variable=variable, expression=arguments[param])
                    variables.add(variable);variable_nodes[variable] = tail[0];names[param] = variable
                tail = walk(statements, tail, inner, aliases=names, namespace=prefix, calls=(*calls, name))
            elif op in ('repeat', 'foreach') and body:
                expansions += 1
                expansion = expansions
                if op == 'repeat':
                    if len(w) != 2 or not re.fullmatch(r'\d{1,2}', w[1]) or not 1 <= int(w[1]) <= 32:
                        fail(node, 'Use repeat COUNT with a literal count from 1 to 32.')
                    count, sequence = int(w[1]), None
                else:
                    header = source[node['range']['start']:node['range']['header_end']].strip()
                    match = re.fullmatch(r'foreach\s+([A-Za-z_][\w-]*)\s+in\s+(.+)\s+limit\s+(\d{1,2})', header)
                    if not match or not 1 <= int(match[3]) <= 32:
                        fail(node, 'Use foreach NAME in EXPRESSION limit COUNT, from 1 to 32.')
                    local_name(match[1]);count = int(match[3])
                    sequence = f'_matrix_{expansion}_items'
                    tail = emit(node, 'value', tail, scope, variable=sequence,
                        expression=compiled(node, match[2], aliases, bool(calls)), collection_limit=count)
                    variables.add(sequence);variable_nodes[sequence] = tail[0]
                for index in range(count):
                    prefix = f'_matrix_{expansion}_{index}_'
                    inner = {**scope, 'iterations': [*scope.get('iterations', []), {'line': node['line'], 'index': index, 'limit': count}]}
                    names = dict(aliases)
                    if sequence:
                        guard = ['binary', '>', ['call', 'length', [['ref', sequence]]], ['literal', index]]
                        inner['conditions'] = [*scope.get('conditions', []), guard]
                        item = f'_matrix_{expansion}_item_{index}'
                        tail = emit(node, 'value', tail, inner, variable=item, expression=['index', ['ref', sequence], ['literal', index]])
                        variables.add(item);variable_nodes[item] = tail[0];names[match[1]] = item
                    position = f'_matrix_{expansion}_index_{index}'
                    tail = emit(node, 'value', tail, inner, variable=position, expression=['literal', index])
                    variables.add(position);variable_nodes[position] = tail[0];names['index'] = position
                    tail = walk(body, tail, inner, aliases=names, namespace=prefix, calls=calls)
            elif op in ('run', 'fetch') and len(w) == 2 and body is None:
                if not scope.get('computer'):
                    fail(node, 'A command needs an explicit on "computer" block.')
                tail = emit(node, 'command' if op == 'run' else 'fetch', tail, scope, command=w[1])
            elif op == 'wait' and len(w) == 2 and body is None:
                match = re.fullmatch(r'(\d+)(ms|s|m|h|d)?', w[1])
                if not match:
                    fail(node, 'Use a wait like 60s, 5m or 1h.')
                seconds = int(match[1]) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2] or 's']
                if not 0 <= seconds <= 31 * 86400:
                    fail(node, 'A wait must be between zero and 31 days.')
                tail = emit(node, 'wait', tail, scope, seconds=seconds)
            elif op == 'print' and len(w) == 2 and body is None:
                tail = emit(node, 'print', tail, scope, text=w[1])
            elif op == 'let' and len(w) >= 4 and w[2] == '=' and body is None:
                name = local_name(w[1])
                if name in variables:
                    fail(node, 'Let names must be unique identifiers.')
                ir = expression(node, 'let', aliases, bool(calls))
                tail = emit(node, 'value', tail, scope, variable=name, expression=ir)
                variables.add(name);variable_nodes[name] = tail[0];aliases[w[1]] = name
            elif op == 'save' and len(w) == 4 and w[2] == 'as' and w[1] in ('outputs', 'response') and body is None:
                name = local_name(w[3])
                if name in variables:
                    fail(node, 'Saved names must be unique identifiers.')
                variables.add(name);aliases[w[3]] = name
                subjects = list(tail)
                tail = emit(node, 'save', tail, scope, variable=name, subjects=list(tail))
                variable_nodes[name] = tail[0]
                if len(subjects) == 1 and next(s for s in steps if s['key'] == subjects[0])['kind'] == 'fetch': file_variables.add(name)
            elif op == 'copy' and len(w) == 4 and w[2] == 'to' and body is None:
                name = aliases.get(w[1], w[1])
                if calls and w[1] not in aliases: fail(node, 'Pass copied values as explicit function parameters.')
                if name not in variables or ':' not in w[3]:
                    fail(node, 'Copy a previously saved value to "computer:/directory/".')
                computer, path = w[3].split(':', 1)
                tail = emit(node, 'copy', tail, scope, variable=name, destination=computer, path=path, file_reference=name in file_variables)
            elif op == 'ask' and w[1:2] == ['Iris'] and (len(w) == 3 and body is None or len(w) == 2 and 'prompt' in node):
                prompt = node.get('prompt', w[2] if len(w) == 3 else '')
                if calls and set(re.findall(r'\$([A-Za-z_][\w-]*)', prompt)) - aliases.keys():
                    fail(node, 'Pass prompt values as explicit function parameters.')
                prompt = re.sub(r'\$([A-Za-z_][\w-]*)', lambda m: '$' + aliases.get(m[1], m[1]), prompt)
                if not prompt or len(prompt) > 100_000:
                    fail(node, 'An Iris prompt needs between 1 and 100,000 characters.')
                for ref in re.findall(r'\$([A-Za-z_][\w-]*)', prompt):
                    if ref not in variables:
                        fail(node, f'Unknown saved value ${ref}.')
                tail = emit(node, 'ask', tail, scope, prompt=prompt)
            elif op == 'if' and body is not None:
                ir = expression(node, 'if', aliases, bool(calls))
                tail = walk(body, tail, {**scope, 'conditions': [*scope.get('conditions', []), ir]}, aliases=aliases, namespace=namespace, calls=calls)
                previous_if = ir
            elif w == ['else'] and body is not None and alternate is not None:
                tail = walk(body, tail, {**scope, 'conditions': [*scope.get('conditions', []), ['unary', 'not', alternate]]}, aliases=aliases, namespace=namespace, calls=calls)
            elif w[:2] == ['run', 'matrix'] and len(w) == 3 and (body is None or all(n['words'][:1] == ['with'] for n in body)):
                inputs = [n['words'][1] for n in body or [] if len(n['words']) == 2]
                if calls and set(inputs) - aliases.keys(): fail(node, 'Pass child values as explicit function parameters.')
                if len(inputs) != len(body or []) or any(aliases.get(n, n) not in variables for n in inputs):
                    fail(node, 'Pass previously saved values with with <name>.')
                tail = emit(node, 'child', tail, scope, matrix=w[2], inputs=inputs,
                    input_variables={n: aliases.get(n, n) for n in inputs})
            elif w == ['require', 'approval'] and body is None:
                tail = emit(node, 'approval', tail, scope)
            elif w[:2] == ['generate', 'matrix'] and len(w) == 3 and body is None:
                if not re.fullmatch(r'[A-Za-z_][\w-]{0,63}\.dm', w[2]) or not tail:
                    fail(node, 'Generate a named .dm proposal after an Iris response.')
                tail = emit(node, 'generate', tail, scope, filename=w[2], subjects=list(tail))
            else:
                fail(node, 'Unknown or malformed Matrix statement: ' + op)
        return tail

    program = []
    for node in tree['body']:
        w = node['words']
        if w[:2] == ['budget', 'steps'] and len(w) == 3 and 'body' not in node:
            if 'budgets' in metadata or not re.fullmatch(r'\d{1,3}', w[2]) or not 1 <= int(w[2]) <= 512:
                fail(node, 'Declare budget steps once, from 1 to 512.')
            budgets['steps'] = int(w[2]);metadata['budgets'] = budgets
        elif w[:1] == ['function']:
            declare_function(node)
        elif w[:1] == ['import']:
            if len(w) != 4 or w[2] != 'sha256' or not NAME.fullmatch(w[1]) or w[1].startswith('_matrix_') or w[1] in imports or not re.fullmatch(r'[0-9a-f]{64}', w[3]) or not node.get('body'):
                fail(node, 'Import a uniquely named frozen function bundle with its exact lowercase SHA-256.')
            identity = hashlib.sha256(source[node['body_start']:node['body_end']].encode()).hexdigest()
            if identity != w[3]: fail(node, 'The imported bundle bytes do not match their declared SHA-256.')
            imports[w[1]] = identity
            for child in node['body']:
                if child['words'][:1] != ['function']: fail(child, 'A frozen import contains source-local functions only.')
                declare_function(child, w[1] + '.')
        elif w[0] == 'input' and len(w) == 2 and 'body' not in node:
            if not NAME.fullmatch(w[1]) or w[1] in variables or w[1].startswith('_matrix_'): fail(node, 'Declare unique input names outside the reserved _matrix_ namespace.')
            inputs.append(w[1]);variables.add(w[1])
        elif w[0] in ('description', 'version') and len(w) == 2 and 'body' not in node:
            if w[0] in metadata:
                fail(node, 'Metadata is declared once.')
            metadata[w[0]] = w[1]
        elif w == ['trigger'] and 'body' in node:
            for trigger in node['body']:
                v = trigger['words']
                if v[0] in ('event', 'startup') and len(v) == 2 and 'body' not in trigger:
                    triggers.append({'kind': v[0], 'name': v[1]})
                elif v[0] == 'schedule' and len(v) in (4, 6) and v[2] == 'every' and v[3] in ('day', 'weekday', 'weekend', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'):
                    if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', v[1]) or len(v) == 6 and v[4] != 'zone':
                        fail(trigger, 'Use schedule "08:00" every "weekday" zone "America/Chicago".')
                    from .timing import zone_name
                    zone = v[5] if len(v) == 6 else 'UTC'
                    if not zone_name(zone):
                        fail(trigger, 'Choose an IANA time zone.')
                    triggers.append({'kind': 'schedule', 'time': v[1], 'every': v[3], 'zone': zone})
                elif v[:1] == ['date'] and len(v) == 2:
                    from datetime import datetime
                    try:
                        date = datetime.fromisoformat(v[1])
                        if not date.tzinfo:
                            raise ValueError
                    except ValueError:
                        fail(trigger, 'Use an ISO date with an explicit UTC offset.')
                    triggers.append({'kind': 'date', 'at': v[1]})
                elif v[:1] == ['interval'] and len(v) == 2 and 'body' not in trigger:
                    from .scheduling import interval
                    try: triggers.append(interval(v[1]))
                    except Invalid as exc: fail(trigger, str(exc))
                elif v[:1] == ['cron'] and len(v) in (2, 4) and (len(v) == 2 or v[2] == 'zone') and 'body' not in trigger:
                    from .scheduling import cron
                    try: triggers.append(cron(v[1], v[3] if len(v) == 4 else 'UTC'))
                    except Invalid as exc: fail(trigger, str(exc))
                else:
                    fail(trigger, 'Unknown Matrix trigger.')
        else:
            program.append(node)
    # Even unused definitions are syntax-checked. Imports are embedded frozen
    # bytes, never filesystem/network resolution during parsing or dispatch.
    dependencies = {name: set() for name in functions}
    allowed = {'gateway', 'profile', 'cwd', 'step', 'parallel', 'on', 'repeat', 'foreach', 'call', 'run', 'fetch', 'wait', 'print', 'let', 'save', 'copy', 'ask', 'if', 'else', 'require', 'generate', 'with'}
    for name, (_, statements, _) in functions.items():
        pending = list(statements)
        while pending:
            node = pending.pop();w = node['words']
            if w[0] not in allowed: fail(node, 'Unknown function statement: ' + w[0])
            if w[0] == 'call':
                if len(w) != 2 or w[1] not in functions: fail(node, 'Call an explicitly named declared function.')
                dependencies[name].add(w[1])
            if w[0] in ('let', 'if'):
                header = source[node['range']['start']:node['range']['header_end']].strip()
                match = re.match(r'^let\s+\S+\s*=\s*' if w[0] == 'let' else r'^if\s+', header)
                if not match: fail(node, 'Supply a complete expression.')
                try: matrix_values.compile_expression(header[match.end():].strip())
                except Invalid as exc: fail(node, str(exc))
            pending.extend(node.get('body', []))
    call_depths = {}
    def check_calls(name, chain=()):
        if name in chain or len(chain) >= 8: raise Invalid('Matrix functions cannot recurse or exceed eight call levels.')
        if name not in call_depths:
            depth = 1 + max((check_calls(child, (*chain, name)) for child in dependencies[name]), default=0)
            if depth > 8: raise Invalid('Matrix functions cannot exceed eight call levels.')
            call_depths[name] = depth
        return call_depths[name]
    for name in functions: check_calls(name)
    walk(program)
    indexed = {s['key']: s for s in steps}
    def ancestors(key):
        pending, found = list(indexed[key]['after']), set()
        while pending:
            item = pending.pop()
            if item not in found: found.add(item);pending.extend(indexed[item]['after'])
        return found
    for node in steps:
        references = re.findall(r'\$([A-Za-z_][\w-]*)', node.get('prompt', ''))
        references += [node['variable']] if node['kind'] == 'copy' else list(node.get('input_variables', {}).values())
        if node.get('expression'): references += list(matrix_values.references(node['expression']))
        for condition in node.get('conditions', []): references += list(matrix_values.references(condition))
        if any(name in variable_nodes and variable_nodes[name] not in ancestors(node['key']) for name in references):
            raise Invalid('A saved value must come from a completed dependency, not another parallel branch.')
    if not steps:
        raise Invalid('A Matrix needs at least one executable statement.')
    if len(triggers) > 16:
        raise Invalid('A Matrix supports at most 16 triggers.')
    graph = {**tree, **metadata, 'steps': steps, 'triggers': triggers, 'inputs': inputs}
    graph['budgets'] = budgets
    graph['imports'] = imports
    graph['expression_version'] = matrix_values.VERSION
    graph['plan_sha256'] = hashlib.sha256(json.dumps({'language': tree['language'], 'expression_version': matrix_values.VERSION,
        'steps': steps, 'triggers': triggers, 'inputs': inputs, 'budgets': budgets, 'imports': imports}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return graph


def review_subject(graph, bindings):
    """Review the complete alpha language's exact source, plan and resolved targets."""
    return {'source_sha256': graph['source_sha256'], 'bindings': bindings, 'language': graph['language'],
            'expression_version': graph['expression_version'], 'plan_sha256': graph['plan_sha256']}
