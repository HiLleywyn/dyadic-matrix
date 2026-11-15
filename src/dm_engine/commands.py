"""Bounded argv data: a literal executable and fixed prefix, never shell text."""
import json
from .errors import Invalid
from .values import evaluate

MAX_ARGUMENTS=64
MAX_ARGUMENT_BYTES=16384
MAX_ARGUMENT_LENGTH=4096


def argument_prefix(ir,executable):
    if ir[0]!='array' or len(ir[1])>MAX_ARGUMENTS:
        raise Invalid('Exec args must be an explicit array of at most 64 arguments.')
    prefix=[];dynamic=False
    for item in ir[1]:
        if item[0]=='literal':
            if not isinstance(item[1],str) or '\0' in item[1] or len(item[1])>MAX_ARGUMENT_LENGTH:raise Invalid('Exec arguments must be bounded text without NUL bytes.')
            if not dynamic:prefix.append(item[1])
        else:
            if '--' not in prefix:raise Invalid('Place a literal -- before dynamic data arguments; keep the executable and option prefix literal.')
            dynamic=True
    name=executable.replace('\\','/').rsplit('/',1)[-1].casefold()
    if dynamic and name in ('cmd','cmd.exe'):
        raise Invalid('Dynamic argv data cannot be passed to the Windows command shell.')
    if dynamic and name in ('powershell','powershell.exe','pwsh','pwsh.exe'):
        flags=[value.casefold() for value in prefix]
        index=0
        while index<len(flags) and flags[index] in ('-nologo','-noprofile','-noninteractive'):index+=1
        if flags[index:index+1]!=['-file'] or index+2>=len(prefix):
            raise Invalid('Dynamic PowerShell arguments require a literal -File script, not a command or encoded-command mode.')
    return prefix


def validate_vector(argv):
    if not isinstance(argv,list) or not 1<=len(argv)<=MAX_ARGUMENTS+1 or any(not isinstance(v,str) or '\0' in v or len(v)>MAX_ARGUMENT_LENGTH for v in argv):
        raise Invalid('Exec needs a bounded text argument vector without NUL bytes.')
    if not argv[0] or len(argv[0])>1024 or argv[0].rstrip(' .').lower().endswith(('.cmd','.bat')):
        raise Invalid('Choose a literal executable, not a Windows batch command.')
    try:size=len(json.dumps(argv,ensure_ascii=False).encode('utf-8'))
    except UnicodeError:raise Invalid('Exec arguments must be valid UTF-8 text.') from None
    if size>MAX_ARGUMENT_BYTES:raise Invalid('Exec argument data exceeds 16 KiB.')
    return argv


def validate_argv(spec,argv):
    validate_vector(argv)
    prefix=[spec['executable'],*spec['argument_prefix']]
    if argv[:len(prefix)]!=prefix:raise Invalid('The literal exec program or reviewed argument prefix changed.')
    return argv


def resolve_argv(spec,values):
    arguments=evaluate(spec['arguments'],values)
    if not isinstance(arguments,list):raise Invalid('Exec args must evaluate to an array.')
    return validate_argv(spec,[spec['executable'],*arguments])
