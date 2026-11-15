"""Generate transport schemas from the engine's actual operators and bounds."""
import argparse
import json
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'src'))
from dm_engine import values
from dm_engine.language import MAX_RETRIES, MAX_RETRY_BACKOFF

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
expression = {'$ref':'#/$defs/expression'}
def tuple_(items): return {'type':'array','prefixItems':items,'minItems':len(items),'maxItems':len(items)}
def constant(value): return {'const':value}
calls = [tuple_([constant('call'),constant(name),{'type':'array','items':expression,'minItems':low,'maxItems':high}]) for name,(low,high) in sorted(values.ARITY.items())]
ir = {'oneOf':[
    tuple_([constant('literal'),{'type':['string','number','boolean','null']}]),
    tuple_([constant('ref'),{'type':'string','minLength':1}]),
    tuple_([constant('index'),expression,expression]),
    tuple_([constant('unary'),{'enum':['+','-','not']},expression]),
    tuple_([constant('binary'),{'enum':sorted(values.PRECEDENCE)},expression,expression]),
    tuple_([constant('array'),{'type':'array','items':expression,'maxItems':values.MAX_NODES}]),
    *calls]}
hash_ = {'type':'string','pattern':'^[0-9a-f]{64}$'}
step = {'type':'object','required':['key','kind','after','line'], 'properties':{
    'key':{'type':'string','pattern':'^n[1-9][0-9]*$'},
    'kind':{'enum':['command','exec','fetch','copy','ask','child','generate','value','save','wait','print','approval']},
    'after':{'type':'array','items':{'type':'string'},'maxItems':512},'line':{'type':'integer','minimum':1},
    'expression':expression,'conditions':{'type':'array','items':expression},
    'executable':{'type':'string','minLength':1,'maxLength':1024},'arguments':expression,
    'argument_prefix':{'type':'array','maxItems':64,'items':{'type':'string','maxLength':4096}},
    'failure':{'enum':['stop','continue']},'projection':{'const':'outcome'},
    'retry':{'type':'object','required':['limit','backoff_seconds'],'additionalProperties':False,'properties':{
        'limit':{'type':'integer','minimum':0,'maximum':MAX_RETRIES},
        'backoff_seconds':{'type':'integer','minimum':1,'maximum':MAX_RETRY_BACKOFF}}},
    'iterations':{'type':'array','items':{'type':'object','required':['line','index','limit'],'properties':{'line':{'type':'integer','minimum':1},'index':{'type':'integer','minimum':0,'maximum':31},'limit':{'type':'integer','minimum':1,'maximum':32}}}},
    'calls':{'type':'array','maxItems':8,'items':{'type':'object','required':['name','line','source_sha256'],'properties':{'name':{'type':'string'},'line':{'type':'integer','minimum':1},'source_sha256':hash_}}}}}
plan = {'title':'dm compiled plan','type':'object','required':['language','name','source_sha256','plan_sha256','steps','triggers','inputs','budgets','expression_version','imports'],
    'properties':{'language':constant('dyadic.matrix/1'),'name':{'type':'string','pattern':'^[A-Za-z_][A-Za-z0-9_-]{0,63}$'},
    'source_sha256':hash_,'plan_sha256':hash_,'steps':{'type':'array','minItems':1,'maxItems':512,'items':step},
    'triggers':{'type':'array','maxItems':16,'items':{'type':'object','required':['kind'],'properties':{'kind':{'enum':['event','startup','schedule','date','interval','cron']}}}},
    'inputs':{'type':'array','items':{'type':'string'}},'budgets':{'type':'object','required':['steps'],'properties':{'steps':{'type':'integer','minimum':1,'maximum':512}}},
    'expression_version':constant(values.VERSION),'imports':{'type':'object','additionalProperties':hash_}},'$defs':{'expression':ir}}
policy = {'title':'dm local command policy','type':'object','additionalProperties':False,'required':['format','root','commands'],
    'properties':{'$schema':{'type':'string'},'format':constant(1),'root':{'type':'string','minLength':1},
    'commands':{'type':'array','maxItems':64,'items':{'type':'string','minLength':1,'maxLength':8192}},
    'deny_commands':{'type':'array','maxItems':64,'items':{'type':'string','minLength':1,'maxLength':8192}},
    **{name:{'type':'array','maxItems':64,'items':{'type':'object','additionalProperties':False,'required':['program','prefix'],'properties':{
        'program':{'type':'string','minLength':1,'maxLength':1024},'prefix':{'type':'array','maxItems':64,'items':{'type':'string','maxLength':4096}}}}} for name in ('executables','deny_executables')},
    'max_seconds':{'type':'integer','minimum':1,'maximum':300}}}
for name, schema in [('plan',plan),('policy',policy)]:
    schema = {'$schema':'https://json-schema.org/draft/2020-12/schema', '$id':'https://github.com/HiLleywyn/dyadic-matrix/blob/main/schemas/'+name+'.schema.json', **schema}
    content=json.dumps(schema,indent=2)+'\n';path=root/'schemas'/f'{name}.schema.json'
    if args.check:
        if not path.is_file() or path.read_text(encoding='utf-8')!=content: raise SystemExit('Generated schema is stale: '+name)
    else:path.write_text(content,encoding='utf-8',newline='\n')
print('Checked' if args.check else 'Generated','plan and policy schemas')
