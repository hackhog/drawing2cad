"""Bounded Part 21 parsing and serialization. Ported source is recorded in origins.json."""

import re as sth_p21_re
import math as sth_p21_math

class P21Ref(int): pass
class P21Enum(str): pass
class P21Binary(str): pass
class P21Derived: pass
P21_DERIVED=P21Derived()
class P21Typed:
    def __init__(self,name,args):
        self.name=str(name).upper()
        self.args=list(args)
    def __repr__(self):
        return 'P21Typed('+repr(self.name)+','+repr(self.args)+')'
class P21Records(dict):
    def __init__(self):
        super().__init__()
        self.raw_rhs={}
class _SthP21Parser:
    number=sth_p21_re.compile(r'[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][+-]?\d+)?')
    name=sth_p21_re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
    enum=sth_p21_re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)\.')
    def __init__(self,text,max_bytes,max_records,max_nodes,max_depth,max_string):
        if not isinstance(text,str):raise TypeError('Part21 input must be str')
        if len(text.encode('utf-8'))>max_bytes:raise ValueError('Part21 text exceeds size bound')
        self.text=text;self.n=len(text);self.pos=0;self.look=None;self.last_end=0
        self.max_records=max_records;self.max_nodes=max_nodes;self.max_depth=max_depth
        self.max_string=max_string;self.nodes=0
    def error(self,message,pos=None):
        raise ValueError('Part21 '+message+' at offset '+str(self.pos if pos is None else pos))
    def token(self):
        t=self.text;n=self.n;p=self.pos
        while p<n:
            if t[p].isspace():p+=1;continue
            if t.startswith('/*',p):
                e=t.find('*/',p+2)
                if e<0:self.error('unterminated comment',p)
                p=e+2;continue
            break
        start=p
        if p>=n:self.pos=p;return ('EOF',None,p,p)
        c=t[p]
        if c in "(),;=*$":
            self.pos=p+1;return (c,c,p,p+1)
        if c=="'":
            p+=1;chars=[]
            while p<n:
                if t[p]=="'":
                    if p+1<n and t[p+1]=="'":chars.append("'");p+=2
                    else:
                        p+=1;self.pos=p;return ('STRING',''.join(chars),start,p)
                else:chars.append(t[p]);p+=1
                if len(chars)>self.max_string:self.error('string exceeds bound',start)
            self.error('unterminated string',start)
        if c=='"':
            e=t.find('"',p+1)
            if e<0:self.error('unterminated binary',p)
            value=t[p+1:e]
            if len(value)>self.max_string or not sth_p21_re.fullmatch(r'[0-3][0-9A-Fa-f]*',value):
                self.error('invalid binary literal',p)
            self.pos=e+1;return ('BINARY',value.upper(),p,e+1)
        if c=='#':
            p+=1;e=p
            while e<n and t[e].isdigit():e+=1
            if e==p or e-p>20:self.error('invalid entity reference',start)
            value=int(t[p:e])
            if value<=0:self.error('entity reference must be positive',start)
            self.pos=e;return ('REF',value,start,e)
        if c=='.':
            m=self.enum.match(t,p)
            if m:
                self.pos=m.end();return ('ENUM',m.group(1).upper(),p,m.end())
        if c in '+-.0123456789':
            m=self.number.match(t,p)
            if not m:self.error('invalid numeric token',p)
            raw=m.group(0)
            if len(raw)>256:self.error('numeric token exceeds bound',p)
            if any(x in raw for x in '.eE'):
                value=float(raw)
                if not sth_p21_math.isfinite(value):self.error('non-finite number',p)
            else:value=int(raw)
            self.pos=m.end();return ('NUMBER',value,p,m.end())
        m=self.name.match(t,p)
        if m:
            if len(m.group(0))>256:self.error('identifier exceeds bound',p)
            self.pos=m.end();return ('NAME',m.group(0).upper(),p,m.end())
        self.error('unexpected character '+repr(c),p)
    def peek(self):
        if self.look is None:self.look=self.token()
        return self.look
    def pop(self):
        out=self.peek();self.look=None;self.last_end=out[3];return out
    def expect(self,kind,value=None):
        out=self.pop()
        if out[0]!=kind or (value is not None and out[1]!=value):
            self.error('expected '+repr((kind,value))+'; got '+repr(out[:2]),out[2])
        return out
    def bump(self,depth):
        self.nodes+=1
        if self.nodes>self.max_nodes:self.error('node count exceeds bound')
        if depth>self.max_depth:self.error('nesting depth exceeds bound')
    def args(self,depth):
        self.bump(depth)
        self.expect('(');out=[]
        if self.peek()[0]==')':self.pop();return out
        while True:
            out.append(self.value(depth+1))
            if self.peek()[0]==')':self.pop();return out
            self.expect(',')
    def value(self,depth):
        self.bump(depth);tok=self.peek();kind,val=tok[:2]
        if kind=='(' :return self.args(depth+1)
        self.pop()
        if kind=='REF':return P21Ref(val)
        if kind=='ENUM':return P21Enum(val)
        if kind=='BINARY':return P21Binary(val)
        if kind=='STRING' or kind=='NUMBER':return val
        if kind=='$':return None
        if kind=='*':return P21_DERIVED
        if kind=='NAME':
            if '-' in val:self.error('invalid typed value name',tok[2])
            return P21Typed(val,self.args(depth+1))
        self.error('expected value; got '+repr(tok[:2]),tok[2])
    def entity(self):
        self.bump(0)
        if self.peek()[0]=='NAME':
            typ=self.pop()[1]
            if '-' in typ:self.error('invalid entity name')
            return typ,self.args(1)
        self.expect('(');parts=[]
        while self.peek()[0]!=')':
            typ=self.expect('NAME')[1]
            if '-' in typ:self.error('invalid complex component name')
            parts.append(P21Typed(typ,self.args(1)))
            if len(parts)>self.max_nodes:self.error('complex component bound')
        self.expect(')')
        if not parts:self.error('empty complex entity')
        return '__COMPLEX__',parts
    def find_data(self):
        if getattr(self,'require_exchange',False):
            self.expect('NAME','ISO-10303-21');self.expect(';')
            self.expect('NAME','HEADER');self.expect(';')
            header_count=0
            while self.peek()[:2]!=('NAME','ENDSEC'):
                self.expect('NAME');self.args(1);self.expect(';');header_count+=1
            if not header_count:self.error('HEADER must contain at least one record')
            self.pop();self.expect(';')
            self.expect('NAME','DATA')
            if self.peek()[0]=='(':self.args(1)
            self.expect(';');return
        nesting=0
        while True:
            tok=self.pop()
            if tok[0]=='EOF':self.error('DATA section missing')
            if tok[0]=='(':
                nesting+=1
                if nesting>self.max_depth:self.error('header nesting bound')
            elif tok[0]==')':
                nesting-=1
                if nesting<0:self.error('unbalanced header')
            elif nesting==0 and tok[0]=='NAME' and tok[1]=='DATA':
                if self.peek()[0]=='(':self.args(1)
                self.expect(';');return
    def parse(self):
        self.find_data();out=P21Records()
        while True:
            token=self.peek()
            if token[0]=='NAME' and token[1]=='ENDSEC':
                self.pop();self.expect(';');break
            ident=self.expect('REF')[1]
            if ident in out:self.error('duplicate entity #'+str(ident))
            if len(out)>=self.max_records:self.error('record count exceeds bound')
            self.expect('=');start=self.peek()[2]
            out[ident]=self.entity();end=self.last_end
            out.raw_rhs[ident]=self.text[start:end]
            self.expect(';')
        if getattr(self,'require_exchange',False):
            if self.peek()[:2]==('NAME','DATA'):self.error('multiple DATA sections are unsupported')
            self.expect('NAME','END-ISO-10303-21');self.expect(';');self.expect('EOF')
            return out
        # Detect unsupported additional DATA sections without reading their entities.
        nesting=0
        while self.peek()[0]!='EOF':
            tok=self.pop()
            if tok[0]=='(':nesting+=1
            elif tok[0]==')':nesting-=1
            if nesting>self.max_depth or nesting<0:self.error('invalid trailer nesting')
            if nesting==0 and tok[0]=='NAME' and tok[1]=='DATA':
                self.error('multiple DATA sections are unsupported')
        if nesting:self.error('unbalanced trailer')
        return out

def sth_p21_parse(text,max_bytes=33554432,max_records=200000,max_nodes=2000000,max_depth=128,max_string=1048576,exchange=False):
    bounds=[max_bytes,max_records,max_nodes,max_depth,max_string]
    if any(not isinstance(x,int) or isinstance(x,bool) or x<=0 for x in bounds):raise ValueError('Part21 bounds must be positive integers')
    if max_depth>256:raise ValueError('Part21 max_depth must be <=256')
    parser=_SthP21Parser(text,*bounds)
    parser.require_exchange=exchange
    return parser.parse()

def sth_p21_refs(value):
    refs=set();stack=[(value,0)];seen=0
    while stack:
        item,depth=stack.pop();seen+=1
        if seen>2000000 or depth>256:raise ValueError('Part21 reference traversal exceeds bounds')
        if isinstance(item,P21Ref):refs.add(int(item))
        elif isinstance(item,P21Typed):stack.extend((x,depth+1) for x in item.args)
        elif isinstance(item,dict):stack.extend((x,depth+1) for x in item.values())
        elif isinstance(item,(list,tuple)):stack.extend((x,depth+1) for x in item)
    return refs

def sth_p21_validate_refs(records):
    missing=sth_p21_refs(records)-set(records)
    if missing:raise ValueError('Part21 dangling references: '+str(sorted(missing)[:100]))
    return True

def sth_p21_dump(value,_depth=0):
    if _depth>256:raise ValueError('Part21 dump nesting bound')
    if isinstance(value,P21Ref):
        if int(value)<=0:raise ValueError('Part21 reference must be positive')
        return '#'+str(int(value))
    if isinstance(value,P21Enum):
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value):raise ValueError('Invalid Part21 enum')
        return '.'+value.upper()+'.'
    if isinstance(value,P21Binary):
        if not sth_p21_re.fullmatch(r'[0-3][0-9A-Fa-f]*',value):raise ValueError('Invalid Part21 binary')
        return '"'+value.upper()+'"'
    if isinstance(value,P21Typed):
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value.name):raise ValueError('Invalid typed name')
        return value.name.upper()+sth_p21_dump(value.args,_depth+1)
    if isinstance(value,P21Derived):return '*'
    if value is None:return '$'
    if isinstance(value,bool):raise TypeError('Use P21Enum for logical values')
    if isinstance(value,int):return str(value)
    if isinstance(value,float):
        if not sth_p21_math.isfinite(value):raise ValueError('Part21 non-finite number')
        text=format(value,'.17g').upper()
        return text if '.' in text or 'E' in text else text+'.'
    if isinstance(value,str):return "'"+value.replace("'","''")+"'"
    if isinstance(value,(list,tuple)):return '('+','.join(sth_p21_dump(x,_depth+1) for x in value)+')'
    raise TypeError('Unsupported Part21 value '+type(value).__name__)

def sth_p21_record(ident,typ,args):
    if not isinstance(ident,int) or isinstance(ident,bool) or ident<=0:raise ValueError('Invalid entity id')
    if typ=='__COMPLEX__':
        if not args or not all(isinstance(x,P21Typed) for x in args):raise ValueError('Invalid complex entity')
        rhs='('+' '.join(sth_p21_dump(x) for x in args)+')'
    else:
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',typ):raise ValueError('Invalid entity name')
        if not isinstance(args,(list,tuple)):raise ValueError('Entity args must be a sequence')
        rhs=typ.upper()+sth_p21_dump(args)
    return '#'+str(ident)+'='+rhs+';'
