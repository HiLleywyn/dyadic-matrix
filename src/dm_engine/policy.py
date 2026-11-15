"""Explicit local command grants. This is a policy boundary, not an OS sandbox."""
import hashlib
import json
from pathlib import Path
from .errors import Invalid


class Policy:
    def __init__(self, path):
        self.path = Path(path).resolve()
        content = self.path.read_bytes()
        if len(content) > 65536: raise Invalid('Local policy exceeds its size bound.')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result: raise Invalid('Local policy contains duplicate fields.')
                result[key] = value
            return result
        try: value = json.loads(content, object_pairs_hook=pairs)
        except (ValueError, UnicodeError): raise Invalid('Local policy must be valid UTF-8 JSON.') from None
        if not isinstance(value, dict) or set(value) - {'format', 'root', 'commands', 'deny_commands', 'executables', 'deny_executables', 'max_seconds', '$schema'} or type(value.get('format')) is not int or value['format'] != 1:
            raise Invalid('Use the documented local policy format and fields.')
        root = value.get('root')
        if not isinstance(root, str) or not root or '\0' in root: raise Invalid('Choose an explicit policy root directory.')
        self.root = (self.path.parent / root).resolve()
        if not self.root.is_dir(): raise Invalid('The policy root directory is unavailable.')
        self.commands, self.denied = value.get('commands', []), value.get('deny_commands', [])
        for group in (self.commands, self.denied):
            if not isinstance(group, list) or len(group) > 64 or any(not isinstance(c, str) or not 1 <= len(c) <= 8192 or '\0' in c for c in group):
                raise Invalid('Policy commands must be a bounded list of exact command strings.')
        self.executables,self.denied_executables=value.get('executables',[]),value.get('deny_executables',[])
        for group in (self.executables,self.denied_executables):
            if not isinstance(group,list) or len(group)>64:raise Invalid('Exec grants must be a bounded list of program/prefix objects.')
            for entry in group:
                if not isinstance(entry,dict) or set(entry)!={'program','prefix'} or not isinstance(entry['program'],str) or not 1<=len(entry['program'])<=1024 or '\0' in entry['program']:
                    raise Invalid('An exec grant names an exact program and literal prefix.')
                if not isinstance(entry['prefix'],list) or len(entry['prefix'])>64 or any(not isinstance(v,str) or len(v)>4096 or '\0' in v for v in entry['prefix']):
                    raise Invalid('An exec grant prefix is a bounded text array.')
        self.seconds = value.get('max_seconds', 30)
        if type(self.seconds) is not int or not 1 <= self.seconds <= 300: raise Invalid('Choose a local timeout from 1 to 300 seconds.')
        self.sha256 = hashlib.sha256(content).hexdigest()

    def directory(self,spec):
        if spec.get('computer') != 'local' or spec.get('gateway', 'dyadic') not in ('dyadic', 'local') or spec.get('profile', 'default') != 'default':
            raise Invalid('The local command adapter requires the explicit local computer and default profile.')
        cwd = (self.root / spec.get('cwd', '.')).resolve()
        if not cwd.is_relative_to(self.root) or not cwd.is_dir(): raise Invalid('The reviewed working directory is outside the policy root or unavailable.')
        return cwd

    def command(self, spec):
        cwd=self.directory(spec);command=spec['command']
        if command in self.denied or command not in self.commands: raise Invalid('The exact command is not permitted by the local policy.')
        return command, cwd

    def argv_command(self,spec,argv=None):
        from .commands import validate_argv
        cwd=self.directory(spec)
        grant={'program':spec['executable'],'prefix':spec['argument_prefix']}
        if grant in self.denied_executables or grant not in self.executables:raise Invalid('The exec program and literal argument prefix are not permitted by the local policy.')
        if argv is not None:validate_argv(spec,argv)
        return cwd

    def review(self, graph):
        effects = []
        for spec in graph['steps']:
            if spec['kind'] == 'command':
                self.command(spec);effects.append(spec)
            elif spec['kind']=='exec':
                self.argv_command(spec);effects.append(spec)
            elif spec['kind'] not in ('value', 'print', 'save', 'wait', 'approval'):
                raise Invalid('This local adapter does not expose the requested effect. Use an explicitly configured host adapter.')
        return {'local/default': {'policy_sha256': self.sha256, 'root': str(self.root), 'timeout_seconds': self.seconds,
                                  'commands': sorted(set(self.commands)), 'deny_commands': sorted(set(self.denied)),
                                  **({'executables':self.executables,'deny_executables':self.denied_executables} if self.executables or self.denied_executables else {})}}, effects
