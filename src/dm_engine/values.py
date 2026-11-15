"""Versioned, bounded pure Matrix expressions. No host evaluation or effects.

The JSON IR is frozen into the reviewed graph. Only JSON data crosses this owner;
collection bodies bind $item/$index lexically, never host functions or attributes.
"""
from __future__ import annotations

import json
import math
import re
from .errors import Invalid

VERSION = 'dyadic.matrix.values/1'
MAX_BYTES = 65536
MAX_ITEMS = 1024
MAX_DEPTH = 32
MAX_NODES = 256
MAX_WORK = 20000
MAX_NUMBER = 2**53 - 1
TOKEN = re.compile(r'\s+|(?P<string>"(?:[^"\\]|\\.)*")|(?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|'
                   r'(?P<ref>\$[A-Za-z_][\w-]*)|(?P<name>[A-Za-z_][A-Za-z_0-9-]*)|'
                   r'(?P<op>==|!=|<=|>=|[+*/%<>()\[\],.\-])')
PRECEDENCE = {'or': 1, 'and': 2, '==': 3, '!=': 3, '<': 4, '<=': 4, '>': 4, '>=': 4,
              '+': 5, '-': 5, '*': 6, '/': 6, '%': 6}
ARITY = {'json': (1, 1), 'text': (1, 1), 'get': (2, 3), 'has': (2, 2), 'length': (1, 1),
         'keys': (1, 1), 'values': (1, 1), 'object': (0, 32), 'set': (3, 3), 'concat': (2, 16),
         'sum': (1, 1), 'min': (1, 1), 'max': (1, 1), 'unique': (1, 1),
         'map': (2, 2), 'filter': (2, 2), 'group': (2, 2), 'sort': (1, 2)}
COLLECTIONS = {'map', 'filter', 'group', 'sort'}


def data(value):
    """Validate before recursion/copying; Python booleans are not Matrix numbers."""
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop();count += 1
        if depth > MAX_DEPTH or count > MAX_WORK:
            raise Invalid('Matrix data is nested too deeply or contains too many values.')
        if item is None or type(item) is bool: continue
        if type(item) in (int, float):
            if abs(item) > MAX_NUMBER or type(item) is float and not math.isfinite(item):
                raise Invalid('Matrix numbers must be finite and within the safe numeric range.')
        elif type(item) is str:
            if len(item) > MAX_BYTES: raise Invalid('Matrix text exceeds its processing bound.')
        elif type(item) in (list, dict):
            if len(item) > MAX_ITEMS: raise Invalid('A Matrix collection contains at most 1024 items.')
            if type(item) is dict and any(type(k) is not str for k in item):
                raise Invalid('Matrix object keys must be text.')
            pending.extend((v, depth + 1) for v in (item.values() if type(item) is dict else item))
        else: raise Invalid('Matrix expressions accept JSON data only.')
    try: encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, UnicodeError): raise Invalid('Matrix data must be finite UTF-8 JSON.') from None
    if len(encoded) > MAX_BYTES: raise Invalid('Matrix data exceeds its 64 KiB processing bound.')
    return value


def compile_expression(source):
    if not isinstance(source, str) or len(source) > 8192:
        raise Invalid('A Matrix expression contains at most 8192 characters.')
    tokens, position = [], 0
    for match in TOKEN.finditer(source):
        if match.start() != position: raise Invalid('Invalid Matrix expression syntax.')
        position = match.end()
        if not match.group().isspace(): tokens.append((match.lastgroup, match.group()))
    if position != len(source) or not tokens: raise Invalid('Supply a complete Matrix expression.')
    index, nodes = 0, 0

    def peek(text): return index < len(tokens) and tokens[index][1] == text
    def consume(text):
        nonlocal index
        if not peek(text): raise Invalid('Expected ' + text + ' in Matrix expression.')
        index += 1
    def node(op, *args):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES: raise Invalid('A Matrix expression contains at most 256 nodes.')
        return [op, *args]
    def expression(minimum=0, depth=0):
        nonlocal index
        if depth > MAX_DEPTH or index >= len(tokens): raise Invalid('Incomplete or deeply nested Matrix expression.')
        kind, text = tokens[index];index += 1
        if text in ('-', '+', 'not'):
            left = node('unary', text, expression(7, depth + 1))
        elif text == '(':
            left = expression(0, depth + 1);consume(')')
        elif text == '[':
            items = []
            if not peek(']'):
                while True:
                    items.append(expression(0, depth + 1))
                    if not peek(','): break
                    consume(',')
            consume(']');left = node('array', items)
        elif kind == 'string':
            try: value = json.loads(text)
            except ValueError: raise Invalid('Invalid Matrix quoted text.') from None
            left = node('literal', data(value))
        elif kind == 'number':
            if len(text) > 64: raise Invalid('A Matrix numeric literal is too large.')
            left = node('literal', data(float(text) if any(c in text for c in '.eE') else int(text)))
        elif kind == 'ref': left = node('ref', text[1:])
        elif text in ('true', 'false', 'null'): left = node('literal', {'true': True, 'false': False, 'null': None}[text])
        elif kind == 'name' and text in ARITY:
            consume('(');args = []
            if not peek(')'):
                while True:
                    args.append(expression(0, depth + 1))
                    if not peek(','): break
                    consume(',')
            consume(')')
            low, high = ARITY[text]
            if not low <= len(args) <= high: raise Invalid('Wrong number of arguments for Matrix ' + text + '.')
            left = node('call', text, args)
        elif kind == 'name' and not peek('('): left = node('ref', text)
        else: raise Invalid('Unknown Matrix expression name or operator.')
        while index < len(tokens):
            if peek('.'):
                consume('.')
                if index >= len(tokens) or tokens[index][0] != 'name': raise Invalid('Choose an object property after a dot.')
                key = tokens[index][1];index += 1;left = node('index', left, node('literal', key))
            elif peek('['):
                consume('[');key = expression(0, depth + 1);consume(']');left = node('index', left, key)
            else:
                operator = tokens[index][1];priority = PRECEDENCE.get(operator, -1)
                if priority < minimum: break
                index += 1;left = node('binary', operator, left, expression(priority + 1, depth + 1))
        return left

    result = expression()
    if index != len(tokens): raise Invalid('Unexpected text after Matrix expression.')
    # Left-associated operators can be deeper than the parser's call stack.
    def depth_check(value, depth=0):
        if depth > MAX_DEPTH: raise Invalid('Matrix expression is nested too deeply.')
        for child in value:
            if isinstance(child, list): depth_check(child, depth + 1)
    depth_check(result)
    return result


def references(ir, bound=frozenset()):
    op = ir[0]
    if op == 'ref': return {ir[1]} - bound
    if op == 'literal': return set()
    if op == 'array': return set().union(*(references(item, bound) for item in ir[1]))
    if op == 'call':
        name, args = ir[1:]
        return set().union(*(references(item, bound | {'item', 'index'} if name in COLLECTIONS and i == 1 else bound) for i, item in enumerate(args)))
    return set().union(*(references(item, bound) for item in ir[1:] if isinstance(item, list)))


def rename(ir, aliases, bound=frozenset()):
    """Qualify compiler-expanded locals without capturing collection bindings."""
    op = ir[0]
    if op == 'ref': return ['ref', ir[1] if ir[1] in bound else aliases.get(ir[1], ir[1])]
    if op == 'literal': return ir
    if op == 'array': return ['array', [rename(item, aliases, bound) for item in ir[1]]]
    if op == 'call':
        name, args = ir[1:]
        return ['call', name, [rename(item, aliases, bound | {'item', 'index'} if name in COLLECTIONS and i == 1 else bound) for i, item in enumerate(args)]]
    return [op, *(rename(item, aliases, bound) if isinstance(item, list) else item for item in ir[1:])]


def evaluate(ir, values):
    """Evaluate only compiler-created IR with a per-step aggregate work meter."""
    data(values)
    work = 0
    def spend(amount=1):
        nonlocal work
        work += amount
        if work > MAX_WORK: raise Invalid('Matrix expression exceeded its processing budget.')
    def boolean(value):
        if type(value) is not bool: raise Invalid('A Matrix condition must be a boolean.')
        return value
    def number(value):
        if type(value) not in (int, float): raise Invalid('Matrix arithmetic requires numbers.')
        return value
    def collection(value):
        if type(value) is not list: raise Invalid('This Matrix operation requires an array.')
        return value
    def lookup(value, key):
        if type(value) is dict and type(key) is str and key in value: return value[key]
        if type(value) is list and type(key) is int and 0 <= key < len(value): return value[key]
        raise Invalid('A Matrix property or array item is unavailable; use has/get for optional data.')
    def equal(a, b):
        if type(a) in (int, float) and type(b) in (int, float): return a == b
        if type(a) is not type(b): return False
        if type(a) is list: return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        if type(a) is dict: return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
        return a == b
    def identity(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    def visit(tree, scope, depth=0):
        spend()
        if depth > MAX_DEPTH: raise Invalid('Matrix expression is nested too deeply.')
        op = tree[0]
        def sub(item): return visit(item, scope, depth + 1)
        if op == 'literal': return tree[1]
        if op == 'ref':
            if tree[1] not in scope: raise Invalid('A referenced Matrix value is unavailable.')
            return scope[tree[1]]
        if op == 'array': return data([sub(item) for item in tree[1]])
        if op == 'index': return lookup(sub(tree[1]), sub(tree[2]))
        if op == 'unary':
            value = sub(tree[2])
            return not boolean(value) if tree[1] == 'not' else data(-number(value) if tree[1] == '-' else number(value))
        if op == 'binary':
            operator, lhs, rhs = tree[1:];a = sub(lhs)
            if operator == 'and': return boolean(a) and boolean(sub(rhs))
            if operator == 'or': return boolean(a) or boolean(sub(rhs))
            b = sub(rhs)
            if operator in ('==', '!='):
                spend(len(identity(a)) + len(identity(b)))
                return equal(a, b) == (operator == '==')
            if operator in ('<', '<=', '>', '>='):
                if not (type(a) is str and type(b) is str): number(a);number(b)
                return {'<': lambda: a < b, '<=': lambda: a <= b, '>': lambda: a > b, '>=': lambda: a >= b}[operator]()
            if operator == '+' and type(a) is type(b) is str: return data(a + b)
            number(a);number(b)
            if operator in ('/', '%') and b == 0: raise Invalid('Matrix arithmetic cannot divide by zero.')
            return data({'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b, '/': lambda: a / b, '%': lambda: a % b}[operator]())
        if op != 'call': raise Invalid('Unsupported Matrix expression IR.')
        name, args = tree[1:]
        if name in COLLECTIONS:
            items = collection(sub(args[0]));spend(len(items))
            if name == 'sort' and len(args) == 1: keys = items
            else: keys = [visit(args[1], {**scope, 'item': item, 'index': index}, depth + 1) for index, item in enumerate(items)]
            if name == 'map': result = keys
            elif name == 'filter': result = [item for item, keep in zip(items, keys) if boolean(keep)]
            elif name == 'group':
                result = {}
                for item, key in zip(items, keys):
                    if type(key) is not str: raise Invalid('Matrix group keys must be text.')
                    result.setdefault(key, []).append(item)
            else:
                if not all(type(k) is str for k in keys):
                    for key in keys: number(key)
                result = [item for _, item in sorted(zip(keys, items), key=lambda pair: pair[0])]
            return data(result)
        # get's explicit fallback is evaluated only when needed.
        if name in ('get', 'has'):
            value, key = sub(args[0]), sub(args[1])
            if type(value) is not dict or type(key) is not str: raise Invalid('Matrix get/has require an object and a text key.')
            if name == 'has': return key in value
            if key in value: return value[key]
            if len(args) == 3: return sub(args[2])
            raise Invalid('A Matrix property is unavailable.')
        values_ = [sub(item) for item in args];value = values_[0] if values_ else None
        if name == 'json':
            if type(value) is not str: raise Invalid('Matrix json requires text.')
            try: result = json.loads(value)
            except (ValueError, RecursionError): raise Invalid('Matrix json requires valid bounded JSON.') from None
        elif name == 'text': result = identity(value)
        elif name == 'length':
            if type(value) not in (list, dict, str): raise Invalid('Matrix length requires text, an array or an object.')
            result = len(value)
        elif name in ('keys', 'values'):
            if type(value) is not dict: raise Invalid('Matrix keys/values require an object.')
            result = sorted(value) if name == 'keys' else [value[k] for k in sorted(value)]
        elif name == 'object':
            result = {}
            for pair in values_:
                if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str or pair[0] in result:
                    raise Invalid('Matrix object requires unique [text, value] pairs.')
                result[pair[0]] = pair[1]
        elif name == 'set':
            if type(value) is not dict or type(values_[1]) is not str: raise Invalid('Matrix set requires an object and text key.')
            result = {**value, values_[1]: values_[2]}
        elif name == 'concat':
            for item in values_: collection(item)
            result = [element for item in values_ for element in item]
        elif name == 'unique':
            seen, result = set(), []
            for item in collection(value):
                key = identity(item);spend(len(key))
                if key not in seen: result.append(item);seen.add(key)
        elif name in ('sum', 'min', 'max'):
            for item in collection(value): number(item)
            if not value and name != 'sum': raise Invalid('Matrix min/max require a nonempty array.')
            result = {'sum': sum, 'min': min, 'max': max}[name](value)
        else: raise Invalid('Unsupported Matrix data function.')
        spend(len(identity(result)))
        return data(result)
    return data(visit(ir, values))
